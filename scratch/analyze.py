import os
import ast
import json

TARGET_DIRS = ["backend/auth", "backend/case", "backend/bot", "backend/citizen-bff"]

class ModuleAnalyzer(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.imports = []
        self.classes = []
        self.functions = []
        self.endpoints = []

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module if node.module else ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef) or isinstance(n, ast.AsyncFunctionDef)]
        self.classes.append({"name": node.name, "methods": methods})
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._check_endpoint(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_endpoint(node)
        self.generic_visit(node)

    def _check_endpoint(self, node):
        decorators = []
        is_endpoint = False
        method = ""
        path = ""
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr in ["get", "post", "put", "delete", "patch"]:
                    is_endpoint = True
                    method = dec.func.attr.upper()
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        path = dec.args[0].value
        if is_endpoint:
            self.endpoints.append({"function": node.name, "method": method, "path": path})
        else:
            self.functions.append(node.name)


def analyze_directory(directory):
    results = []
    for root, dirs, files in os.walk(directory):
        if "venv" in root or ".venv" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    try:
                        tree = ast.parse(f.read())
                        analyzer = ModuleAnalyzer(path)
                        analyzer.visit(tree)
                        results.append({
                            "file": path,
                            "imports": analyzer.imports,
                            "classes": analyzer.classes,
                            "functions": analyzer.functions,
                            "endpoints": analyzer.endpoints
                        })
                    except Exception as e:
                        print(f"Error parsing {path}: {e}")
    return results

inventory = {}
for d in TARGET_DIRS:
    inventory[d] = analyze_directory(d)

with open("scratch/inventory.json", "w") as f:
    json.dump(inventory, f, indent=2)

print("Inventory generated at scratch/inventory.json")
