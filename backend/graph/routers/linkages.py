from fastapi import APIRouter, Request, Query, HTTPException
from typing import Optional
from response_helpers import success_response, error_response

router = APIRouter(prefix="/graph", tags=["Graph"])


@router.get("/linkages")
async def get_linkages(
    request: Request,
    entityId: str,
    entityType: Optional[str] = None,
    hops: int = Query(2, ge=1, le=3),
    cursor: Optional[str] = None,
    limit: int = 50
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    driver = request.app.state.neo4j_driver

    # Better query to extract distinct nodes and edges
    query = f"""
    MATCH (anchor:Entity {{id: $entityId}})
    CALL apoc.path.subgraphAll(anchor, {{
        maxLevel: $hops
    }})
    YIELD nodes, relationships
    RETURN anchor, nodes, relationships
    """
    
    # Alternatively without APOC if APOC is not available:
    query = f"""
    MATCH p = (anchor:Entity {{id: $entityId}})-[*1..{hops}]-(linked)
    WITH anchor, collect(nodes(p)) AS paths_nodes, collect(relationships(p)) AS paths_rels
    WITH anchor, 
         apoc.coll.toSet(apoc.coll.flatten(paths_nodes)) AS all_nodes, 
         apoc.coll.toSet(apoc.coll.flatten(paths_rels)) AS all_rels
    RETURN anchor, all_nodes, all_rels
    """
    
    # Pure Cypher without APOC:
    query = f"""
    MATCH (anchor:Entity {{id: $entityId}})
    OPTIONAL MATCH p = (anchor)-[*1..{hops}]-(linked)
    UNWIND (CASE WHEN p IS NULL THEN [null] ELSE nodes(p) END) AS n
    WITH anchor, collect(DISTINCT n) AS all_nodes, collect(DISTINCT p) AS paths
    UNWIND (CASE WHEN paths = [] THEN [null] ELSE paths END) AS p
    UNWIND (CASE WHEN p IS NULL THEN [null] ELSE relationships(p) END) AS r
    WITH anchor, all_nodes, collect(DISTINCT r) AS all_rels
    RETURN anchor, 
           [node IN all_nodes WHERE node IS NOT NULL AND id(node) <> id(anchor)] AS nodes, 
           [rel IN all_rels WHERE rel IS NOT NULL] AS edges
    """
    
    async with driver.session() as session:
        # Check if anchor exists
        result = await session.run("MATCH (anchor:Entity {id: $entityId}) RETURN anchor", entityId=entityId)
        anchor_record = await result.single()
        if not anchor_record:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content=error_response("ENTITY_NOT_FOUND", "Entity not found in graph", correlation_id))

        anchor_node = anchor_record["anchor"]
        
        # Execute linkage query
        result = await session.run(query, entityId=entityId)
        record = await result.single()

    anchor_labels = list(anchor_node.labels)
    anchor_type = [l for l in anchor_labels if l != "Entity"][0] if len(anchor_labels) > 1 else "UNKNOWN"
    
    nodes_out = []
    edges_out = []
    
    if record:
        for node in record["nodes"]:
            labels = list(node.labels)
            n_type = [l for l in labels if l != "Entity"][0] if len(labels) > 1 else "UNKNOWN"
            # Hops logic could be added by another query, but for now we simplify
            nodes_out.append({
                "id": node.get("id"),
                "type": n_type.upper(),
                "fraudScore": node.get("fraudScore", 0),
                "hopsFromAnchor": 1 # Simplified
            })
            
        for rel in record["edges"]:
            edges_out.append({
                "from": rel.nodes[0].get("id"),
                "to": rel.nodes[1].get("id"),
                "relation": rel.type,
                "count": rel.get("count", 1),
                "lastSeen": rel.get("lastSeen", "")
            })
    
    response_data = {
        "anchor": {
            "id": anchor_node.get("id"),
            "type": anchor_type.upper(),
            "fraudScore": anchor_node.get("fraudScore", 0)
        },
        "nodes": nodes_out,
        "edges": edges_out,
        "totalNodes": len(nodes_out),
        "totalEdges": len(edges_out)
    }
    
    return {
        "requestId": request.state.request_id if hasattr(request.state, "request_id") else "",
        "correlationId": correlation_id,
        "status": "success",
        "data": response_data,
        "nextCursor": None,
        "hasMore": False,
        "total": len(nodes_out)
    }


@router.get("/shortest-path")
async def get_shortest_path(
    request: Request,
    from_id: str = Query(..., alias="from"),
    to_id: str = Query(..., alias="to")
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    driver = request.app.state.neo4j_driver
    
    query = """
    MATCH p = shortestPath((start:Entity {id: $from_id})-[*]-(end:Entity {id: $to_id}))
    RETURN p
    """
    
    async with driver.session() as session:
        result = await session.run(query, from_id=from_id, to_id=to_id)
        record = await result.single()
        
        if not record:
            return error_response("NO_PATH_FOUND", "No path found between entities", correlation_id)
            
        path = record["p"]
        
    # parse path
    return success_response({
        "found": True,
        "pathLength": len(path),
        "path": []
    }, correlation_id)


@router.get("/global")
async def get_global_graph(request: Request, limit: int = 300):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    driver = request.app.state.neo4j_driver
    
    # Show ONLY confirmed fraud cases (Action_Taken) and their connected entities
    query = f"""
    MATCH (c:Case)
    WHERE c.status = 'Action_Taken' OR c.isConfirmed = true
    OPTIONAL MATCH (c)-[r]-(m:Entity)
    RETURN c.id AS nid, labels(c) AS nlabels, c.fraudScore AS nscore,
           type(r) AS rel_type,
           m.id AS mid, labels(m) AS mlabels, m.fraudScore AS mscore
    LIMIT {limit}
    """
    
    nodes_map = {}
    edges_list = []
    seen_edges = set()
    
    async with driver.session() as session:
        result = await session.run(query)
        async for record in result:
            nid = record.get("nid")
            if nid:
                labels = list(record.get("nlabels") or [])
                ntype = [l for l in labels if l != "Entity"][0] if len(labels) > 1 else "UNKNOWN"
                if nid not in nodes_map:
                    nodes_map[nid] = {
                        "id": nid,
                        "type": ntype.upper(),
                        "fraudScore": record.get("nscore") or 0
                    }
            
            mid = record.get("mid")
            if mid:
                labels = list(record.get("mlabels") or [])
                mtype = [l for l in labels if l != "Entity"][0] if len(labels) > 1 else "UNKNOWN"
                if mid not in nodes_map:
                    nodes_map[mid] = {
                        "id": mid,
                        "type": mtype.upper(),
                        "fraudScore": record.get("mscore") or 0
                    }
            
            rel_type = record.get("rel_type")
            if nid and mid and rel_type:
                edge_key = (nid, mid, rel_type)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges_list.append({
                        "from": nid,
                        "to": mid,
                        "relation": rel_type
                    })

    nodes_out = list(nodes_map.values())
    return success_response({
        "nodes": nodes_out,
        "edges": edges_list,
        "totalNodes": len(nodes_out),
        "totalEdges": len(edges_list)
    }, correlation_id)
