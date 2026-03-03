document.addEventListener("DOMContentLoaded", function () {
    const content = document.querySelector(".md-content__inner");
    if (!content) return;

    const h1 = content.querySelector("h1");
    if (!h1 || document.getElementById("study-tools-container")) return;

    // 1. Setup Study Tools Container
    const container = document.createElement("div");
    container.id = "study-tools-container";
    container.style.display = "flex";
    container.style.gap = "10px";
    container.style.marginTop = "15px";
    container.style.marginBottom = "20px";
    container.style.flexWrap = "wrap";

    // 2. PDF Button
    const pdfBtn = document.createElement("button");
    pdfBtn.className = "md-button md-button--primary";
    pdfBtn.innerHTML = '📥 儲存為 PDF';
    pdfBtn.onclick = function () { window.print(); };

    // 3. Memorize Mode Button
    const memBtn = document.createElement("button");
    memBtn.className = "md-button";
    memBtn.innerHTML = '🧠 背誦模式 (遮蔽重點)';
    let memMode = false;
    memBtn.onclick = function () {
        memMode = !memMode;
        if (memMode) {
            memBtn.classList.add("md-button--primary");
        } else {
            memBtn.classList.remove("md-button--primary");
        }
        const bolds = content.querySelectorAll("strong");
        bolds.forEach(b => {
            if (memMode) {
                b.dataset.origBg = b.style.backgroundColor || "";
                b.dataset.origColor = b.style.color || "";
                b.style.backgroundColor = "#111827";
                b.style.color = "#111827";
                b.style.cursor = "pointer";
                b.style.borderRadius = "4px";
                b.style.padding = "0 4px";
                b.onclick = function () {
                    this.style.backgroundColor = this.dataset.origBg;
                    this.style.color = this.dataset.origColor;
                };
            } else {
                b.style.backgroundColor = b.dataset.origBg;
                b.style.color = b.dataset.origColor;
                b.onclick = null;
                b.style.cursor = "auto";
            }
        });
    };

    // 4. Study Progress Tracker
    const statusBtn = document.createElement("button");
    statusBtn.className = "study-status-btn";
    const pageUrl = window.location.pathname;

    // Load existing status from LocalStorage
    let currentStatus = localStorage.getItem("status_" + pageUrl) || "unread";

    const updateStatusUI = () => {
        statusBtn.className = "study-status-btn status-" + currentStatus;
        if (currentStatus === "unread") {
            statusBtn.innerHTML = "📝 未讀";
        } else if (currentStatus === "memorized") {
            statusBtn.innerHTML = "✅ 已熟記";
        } else if (currentStatus === "important") {
            statusBtn.innerHTML = "🔥 必考看十遍";
        }
    };

    updateStatusUI();

    statusBtn.onclick = function () {
        if (currentStatus === "unread") currentStatus = "memorized";
        else if (currentStatus === "memorized") currentStatus = "important";
        else currentStatus = "unread";

        localStorage.setItem("status_" + pageUrl, currentStatus);
        updateStatusUI();
    };

    h1.appendChild(statusBtn);

    // Append Tools
    container.appendChild(pdfBtn);
    container.appendChild(memBtn);
    h1.parentNode.insertBefore(container, h1.nextSibling);

    // 5. Law Referencer (Auto Hyperlink for Laws)
    // 掃描段落文字中的法規條文，並轉換為全國法規資料庫查詢連結
    const lawRegex = /((?:土地法|平均地權條例|土地稅法|民法|契稅條例|房屋稅條例|都市計畫法|區域計畫法|國土計畫法)[^\d第]*第[\s\d\-之]+條)/g;

    const textNodes = [];
    const walk = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while (node = walk.nextNode()) {
        // Skip text inside existing links or code blocks
        if (node.parentNode.nodeName === 'A' || node.parentNode.nodeName === 'CODE' || node.parentNode.nodeName === 'PRE') {
            continue;
        }
        textNodes.push(node);
    }

    textNodes.forEach(node => {
        const text = node.nodeValue;
        if (lawRegex.test(text)) {
            const span = document.createElement('span');
            span.innerHTML = text.replace(lawRegex, function (match) {
                // Encode the law string to search in moj.gov.tw
                const query = encodeURIComponent(match);
                return `<a href="https://law.moj.gov.tw/LawClass/LawSearchResult.aspx?p=A&t=A1A2E1F1&k1=${query}" target="_blank" title="查看全國法規資料庫: ${match}" style="border-bottom: 1px dashed var(--md-accent-fg-color);">${match}</a>`;
            });
            node.parentNode.replaceChild(span, node);
        }
    });

});
