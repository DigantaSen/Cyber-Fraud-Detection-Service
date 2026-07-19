document.addEventListener("DOMContentLoaded", () => {
    
    // --- Mock Data ---
    const mockCases = [
        { id: "CASE-001", uuid: "00000000-0000-0000-0000-000000000001", risk: "high", status: "AWAITING REVIEW", aiScore: 92 },
        { id: "CASE-002", uuid: "00000000-0000-0000-0000-000000000002", risk: "medium", status: "AWAITING REVIEW", aiScore: 65 },
        { id: "CASE-003", uuid: "00000000-0000-0000-0000-000000000003", risk: "high", status: "AWAITING REVIEW", aiScore: 88 }
    ];

    const graphData = {
        nodes: [
            { id: 1, label: 'Suspect: John Doe', group: 'person' },
            { id: 2, label: 'Bank Acct: 1234', group: 'account' },
            { id: 3, label: 'Bank Acct: 5678', group: 'account' },
            { id: 4, label: 'IP: 192.168.1.1', group: 'device' }
        ],
        edges: [
            { from: 1, to: 2, label: 'Owns' },
            { from: 1, to: 3, label: 'Owns' },
            { from: 2, to: 3, label: 'Transfer $50k' },
            { from: 4, to: 1, label: 'Logged In' }
        ]
    };

    const heatmapData = [
        [28.6139, 77.2090, 0.8], // Delhi
        [19.0760, 72.8777, 0.9], // Mumbai
        [12.9716, 77.5946, 0.5]  // Bangalore
    ];

    let network = null;
    let map = null;
    let heat = null;
    let currentCaseUuid = null;

    // --- DOM Elements ---
    const caseQueueEl = document.getElementById("caseQueue");
    const activeCaseIdEl = document.getElementById("activeCaseId");
    const activeCaseStatusEl = document.getElementById("activeCaseStatus");
    const aiVerdictScoreEl = document.getElementById("aiVerdictScore");
    const aiVerdictLabelEl = document.getElementById("aiVerdictLabel");
    const modelFactorsEl = document.getElementById("modelFactors");
    const btnIntelPackage = document.getElementById("btnIntelPackage");
    const justificationInput = document.getElementById("justification");
    const btnApprove = document.getElementById("btnApprove");
    const btnReject = document.getElementById("btnReject");

    // --- Init UI ---
    function init() {
        renderCaseQueue();
        simulateSSE();
        initGraph();
        initMap();
        setupEventListeners();
    }

    function renderCaseQueue() {
        caseQueueEl.innerHTML = "";
        mockCases.forEach(c => appendCase(c));
    }

    function appendCase(c) {
        const el = document.createElement("div");
        el.className = "case-card";
        el.innerHTML = `
            <div class="case-card-header">
                <span class="case-id">${c.id}</span>
                <span>Just now</span>
            </div>
            <h3>Suspicious Transfer</h3>
            <span class="badge ${c.risk === 'high' ? 'high-risk' : 'medium-risk'}">${c.risk} RISK</span>
        `;
        el.addEventListener("click", () => selectCase(c, el));
        caseQueueEl.prepend(el); // Prepend to show at top
    }

    // Mocking SSE (Server-Sent Events) for real-time updates
    function simulateSSE() {
        let caseCounter = 4;
        setInterval(() => {
            const newCase = {
                id: \`CASE-00\${caseCounter}\`,
                uuid: \`00000000-0000-0000-0000-00000000000\${caseCounter}\`,
                risk: Math.random() > 0.5 ? "high" : "medium",
                status: "AWAITING REVIEW",
                aiScore: Math.floor(Math.random() * 40) + 60
            };
            mockCases.push(newCase);
            appendCase(newCase);
            caseCounter++;
        }, 15000); // New case every 15 seconds
    }

    function selectCase(caseObj, element) {
        document.querySelectorAll(".case-card").forEach(el => el.classList.remove("active"));
        element.classList.add("active");
        
        currentCaseUuid = caseObj.uuid;
        
        activeCaseIdEl.textContent = `Case: ${caseObj.id}`;
        activeCaseStatusEl.textContent = caseObj.status;
        activeCaseStatusEl.className = "badge awaiting";
        
        btnIntelPackage.disabled = false;
        
        // Update AI Breakdown
        aiVerdictScoreEl.textContent = `${caseObj.aiScore}%`;
        
        if(caseObj.aiScore > 80) {
            aiVerdictLabelEl.textContent = "FRAUD DETECTED";
            aiVerdictScoreEl.style.color = "var(--danger)";
        } else {
            aiVerdictLabelEl.textContent = "SUSPICIOUS";
            aiVerdictScoreEl.style.color = "var(--warning)";
        }

        modelFactorsEl.innerHTML = `
            <div class="factor-bar">
                <div class="factor-header">
                    <span>Transaction Pattern Anomaly</span>
                    <span>95%</span>
                </div>
                <div class="progress-track"><div class="progress-fill fill-danger" style="width: 0%"></div></div>
            </div>
            <div class="factor-bar">
                <div class="factor-header">
                    <span>Geographic Velocity</span>
                    <span>72%</span>
                </div>
                <div class="progress-track"><div class="progress-fill fill-warning" style="width: 0%"></div></div>
            </div>
        `;

        // Trigger animations
        setTimeout(() => {
            const fills = document.querySelectorAll(".progress-fill");
            if(fills[0]) fills[0].style.width = "95%";
            if(fills[1]) fills[1].style.width = "72%";
        }, 100);

        // Reset Graph and Map view
        if(network) network.fit();
        if(map) map.setView([20.5937, 78.9629], 5);
    }

    function initGraph() {
        const container = document.getElementById("graphContainer");
        const options = {
            nodes: {
                shape: 'dot',
                size: 16,
                font: { color: '#f8fafc', size: 12 }
            },
            edges: {
                color: '#94a3b8',
                font: { color: '#94a3b8', size: 10, align: 'top' },
                arrows: 'to'
            },
            groups: {
                person: { color: { background: '#ef4444', border: '#b91c1c' } },
                account: { color: { background: '#3b82f6', border: '#1d4ed8' } },
                device: { color: { background: '#10b981', border: '#047857' } }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            },
            physics: {
                stabilization: true
            }
        };
        network = new vis.Network(container, graphData, options);
    }

    function initMap() {
        const container = document.getElementById("mapContainer");
        map = L.map(container, {
            zoomControl: false,
            attributionControl: false
        }).setView([20.5937, 78.9629], 4); // India center

        // Dark theme map tiles (CartoDB Dark Matter)
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            maxZoom: 19
        }).addTo(map);

        // Add Heatmap
        heat = L.heatLayer(heatmapData, {
            radius: 25,
            blur: 15,
            gradient: { 0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red' }
        }).addTo(map);
    }

    function setupEventListeners() {
        // Intelligence Package Generation
        btnIntelPackage.addEventListener("click", async () => {
            if(!currentCaseUuid) return;
            const originalText = btnIntelPackage.innerHTML;
            btnIntelPackage.innerHTML = "Generating...";
            btnIntelPackage.disabled = true;

            try {
                // Call Reporting Service (T6b/T7)
                const response = await fetch("http://localhost:8007/reports/intelligence-package", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ case_id: currentCaseUuid })
                });

                if(response.ok) {
                    const data = await response.json();
                    alert("Intelligence Package Generated Successfully!\nSignature: " + data.signature.substring(0,20) + "...");
                } else {
                    alert("Failed to generate package.");
                }
            } catch(e) {
                console.error(e);
                alert("Network error communicating with Reporting Service.");
            }

            btnIntelPackage.innerHTML = originalText;
            btnIntelPackage.disabled = false;
        });

        btnApprove.addEventListener("click", () => handleHitl("APPROVED"));
        btnReject.addEventListener("click", () => handleHitl("REJECTED"));
    }

    function handleHitl(decision) {
        if(!currentCaseUuid) return alert("Select a case first.");
        const reason = justification.value.trim();
        if(!reason) return alert("Justification is mandatory.");

        alert(`Case ${currentCaseUuid} ${decision} with reason: ${reason}`);
        
        // Update UI state
        activeCaseStatusEl.textContent = decision;
        activeCaseStatusEl.className = `badge ${decision === 'APPROVED' ? 'high-risk' : 'awaiting'}`;
        justification.value = "";
    }

    // Initialize
    init();
});
