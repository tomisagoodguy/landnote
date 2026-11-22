function initStudyTools() {
    const content = document.querySelector(".md-content__inner");
    if (!content) return;

    const h1 = content.querySelector("h1");
    // 如果已經初始化過，就不要重複加入元件
    if (!h1 || document.getElementById("study-tools-container")) return;

    const pageUrl = window.location.pathname;

    // Do not show study tools on index pages, categories, tags, or 404 Error page
    const isListOrHome = pageUrl === '/' ||
        pageUrl.endsWith('/landnote/') ||
        pageUrl.endsWith('/tags/') ||
        pageUrl.endsWith('/exams/') ||
        pageUrl.endsWith('/blog/') ||
        pageUrl.includes('/category/');
    const is404 = document.title.includes('404');

    if (isListOrHome || is404) return;

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

    // 3. Study Progress Tracker
    const statusBtn = document.createElement("button");
    statusBtn.className = "study-status-btn";

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
    h1.parentNode.insertBefore(container, h1.nextSibling);

    // 4. Law Referencer (Auto Hyperlink for Laws)
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
}

// 部落格列表無限捲動：捲到底自動載入下一頁文章，分頁列保留給無 JS 環境
function initInfiniteBlog() {
    const pagination = document.querySelector(".md-content .md-pagination");
    if (!pagination || pagination.dataset.infinite) return;
    if (!document.querySelector(".md-post--excerpt")) return;
    if (!("IntersectionObserver" in window)) return;
    pagination.dataset.infinite = "1";

    const nextUrlFrom = (nav, baseUrl) => {
        const current = nav.querySelector(".md-pagination__current");
        let el = current ? current.nextElementSibling : null;
        while (el && !el.matches("a.md-pagination__link")) el = el.nextElementSibling;
        return el ? new URL(el.getAttribute("href"), baseUrl).href : null;
    };

    let nextUrl = nextUrlFrom(pagination, window.location.href);
    if (!nextUrl) return;

    const status = document.createElement("div");
    status.className = "infinite-blog-status";
    status.style.cssText = "text-align:center;padding:1.5rem 0;color:var(--md-default-fg-color--light);";
    pagination.parentNode.insertBefore(status, pagination);
    pagination.style.display = "none";

    let loading = false;

    const absolutize = (root, baseUrl) => {
        root.querySelectorAll("[href]").forEach(el => {
            const v = el.getAttribute("href");
            if (v && !v.startsWith("#")) el.setAttribute("href", new URL(v, baseUrl).href);
        });
        root.querySelectorAll("[src]").forEach(el => {
            el.setAttribute("src", new URL(el.getAttribute("src"), baseUrl).href);
        });
    };

    const loadNext = async () => {
        if (loading || !nextUrl || !status.isConnected) return;
        loading = true;
        status.textContent = "載入更多文章中…";
        const url = nextUrl;
        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error("HTTP " + res.status);
            const doc = new DOMParser().parseFromString(await res.text(), "text/html");
            doc.querySelectorAll(".md-post--excerpt").forEach(post => {
                absolutize(post, url);
                status.parentNode.insertBefore(document.importNode(post, true), status);
            });
            const nav = doc.querySelector(".md-content .md-pagination");
            nextUrl = nav ? nextUrlFrom(nav, url) : null;
            status.textContent = nextUrl ? "" : "已載入全部文章";
            if (!nextUrl) observer.disconnect();
            loading = false;
            // 內容不足以撐滿畫面時繼續載入（只在成功時，避免失敗無限重試）
            if (nextUrl && status.getBoundingClientRect().top < window.innerHeight + 800) loadNext();
        } catch (err) {
            console.error("無限捲動載入失敗:", url, err);
            status.innerHTML = "";
            const retry = document.createElement("button");
            retry.className = "md-button";
            retry.textContent = "載入失敗，點此重試";
            retry.onclick = loadNext;
            status.appendChild(retry);
            loading = false;
        }
    };

    const observer = new IntersectionObserver(entries => {
        if (entries.some(e => e.isIntersecting)) loadNext();
    }, { rootMargin: "0px 0px 800px 0px" });
    observer.observe(status);
}

// 監聽 MkDocs Material 的單頁式導航事件 (instant navigation)
if (typeof document$ !== "undefined") {
    document$.subscribe(function () {
        initStudyTools();
        initInfiniteBlog();
    });
} else {
    document.addEventListener("DOMContentLoaded", function () {
        initStudyTools();
        initInfiniteBlog();
    });
}
