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
        pageUrl.endsWith('/jasper/') ||
        pageUrl.endsWith('/exam-reader/review/') ||  // 複習清單頁：整頁狀態鈕會與題目標記混淆
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
    // 「第34條之1」的「之1」要一起包進連結，否則會查到第 34 條；
    // 法名與「第」之間只容許少數非標點字（「民法物權編第」），否則會從前一個法名一路吃到後面的條號
    const lawRegex = /((?:土地法|平均地權條例|土地稅法|民法|契稅條例|房屋稅條例|都市計畫法|區域計畫法|國土計畫法)[^\d第，。、；：「」『』（）()\n]{0,6}第[\s\d\-之]+條(?:\s*之\s*\d+)?)/g;
    // 全國法規資料庫的查詢頁（LawSearchResult）會被其 WAF 擋下（「含有不允許輸入之字元」），
    // 改直接連到單一條文頁 LawSingle.aspx?pcode=…&flno=34-1；pcode 對照 data/law_timeline.json
    const lawPcodes = {
        "土地法": "D0060001", "平均地權條例": "D0060009", "土地稅法": "G0340096",
        "民法": "B0000001", "契稅條例": "G0340105", "房屋稅條例": "G0340102",
        "都市計畫法": "D0070001", "區域計畫法": "D0070030", "國土計畫法": "D0070230",
    };
    const lawUrl = (match) => {
        const name = Object.keys(lawPcodes).find(n => match.startsWith(n));
        const nums = match.slice(match.lastIndexOf("第")).match(/\d+/g) || [];
        if (!name || !nums.length) return null;
        const flno = nums.slice(0, 2).join("-");
        return `https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=${lawPcodes[name]}&flno=${flno}`;
    };

    const textNodes = [];
    const walk = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while (node = walk.nextNode()) {
        // Skip text inside existing links or code blocks
        // 標題（如依法條比較頁的「土地法第34條之1」）不加連結
        if (node.parentNode.nodeName === 'A' || node.parentNode.nodeName === 'CODE' || node.parentNode.nodeName === 'PRE'
            || node.parentNode.closest('h1, h2, h3, summary')) {  // summary 內有連結會讓點標題變成跳頁而不是展開
            continue;
        }
        textNodes.push(node);
    }

    textNodes.forEach(node => {
        const text = node.nodeValue;
        if (lawRegex.test(text)) {
            const span = document.createElement('span');
            span.innerHTML = text.replace(lawRegex, function (match) {
                const url = lawUrl(match);
                if (!url) return match;
                return `<a href="${url}" target="_blank" rel="noopener" title="查看全國法規資料庫: ${match}" style="border-bottom: 1px dashed var(--md-accent-fg-color);">${match}</a>`;
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

// 題庫／逐題讀的「延伸閱讀」：展開 <details class="qb-read"> 時就地載入文章全文
// toggle 事件不冒泡，用捕獲階段監聽一次即可涵蓋 instant navigation 換頁後的新內容
document.addEventListener("toggle", async function (e) {
    const box = e.target;
    if (!(box instanceof HTMLDetailsElement) || !box.classList.contains("qb-read")) return;
    if (!box.open || box.dataset.loaded) return;
    const link = box.querySelector("a.qb-read-link");
    if (!link) return;
    box.dataset.loaded = "1";
    box.querySelector(".qb-read-body")?.remove();  // 上次載入失敗留下的訊息
    const body = document.createElement("div");
    body.className = "qb-read-body";
    body.textContent = "載入文章中…";
    link.parentElement.before(body);
    try {
        const res = await fetch(link.href);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const doc = new DOMParser().parseFromString(await res.text(), "text/html");
        const article = doc.querySelector(".md-content__inner");
        if (!article) throw new Error("找不到文章內容");
        article.querySelectorAll("h1, .md-source-file, .md-content__button, #study-tools-container")
            .forEach(el => el.remove());
        article.querySelectorAll("[href]").forEach(el => {
            const v = el.getAttribute("href");
            if (v && !v.startsWith("#")) el.setAttribute("href", new URL(v, link.href).href);
        });
        article.querySelectorAll("[src]").forEach(el => {
            el.setAttribute("src", new URL(el.getAttribute("src"), link.href).href);
        });
        body.replaceChildren(...Array.from(article.childNodes).map(n => document.importNode(n, true)));
    } catch (err) {
        console.error("延伸閱讀載入失敗:", link.href, err);
        delete box.dataset.loaded;  // 收合再展開即重試
        body.textContent = "文章載入失敗，請收合後重試，或改按下方「在新頁面開啟」。";
    }
}, true);

// 連續刷題頁（有 .er-drill-src）：一鍵展開／收合全部解答（details.success），偏好記在 localStorage
function initDrillToggle() {
    const article = document.querySelector("article.md-content__inner");
    if (!article || !article.querySelector(".er-drill-src") || article.querySelector(".er-drill-toggle")) return;
    const answers = () => article.querySelectorAll("details.success");
    const KEY = "drill_expand_all";
    let expanded = false;
    try { expanded = localStorage.getItem(KEY) === "1"; } catch (err) { console.warn("讀取展開偏好失敗:", err); }

    const btn = document.createElement("button");
    btn.className = "md-button er-drill-toggle";
    const apply = () => {
        answers().forEach(d => { d.open = expanded; });
        btn.textContent = expanded ? "解答全部收合" : "解答全部展開";
        btn.setAttribute("aria-pressed", String(expanded));
    };
    btn.onclick = function () {
        expanded = !expanded;
        try { localStorage.setItem(KEY, expanded ? "1" : "0"); } catch (err) { console.warn("儲存展開偏好失敗:", err); }
        apply();
    };
    const h1 = article.querySelector("h1");
    (h1 || article.firstChild).after(btn);
    apply();
}

// 逐題讀的熟練度標記：題目卡 .qb-item[data-q] 加「不熟／待複習／熟練」按鈕，存在 localStorage。
// data-q 跨頁面相同（考卷 id-題號），同一題在考卷頁、刷題頁、比較頁共用；狀態名稱對應 Obsidian vault 的「狀態」欄位。
const QM_KEY = "qmark_v1";
const QM_STATES = [["weak", "不熟"], ["review", "待複習"], ["done", "熟練"]];

function qmLoad() {
    try { return JSON.parse(localStorage.getItem(QM_KEY) || "{}"); }
    catch (err) { console.warn("讀取熟練度標記失敗:", err); return {}; }
}

function qmSave(marks) {
    try { localStorage.setItem(QM_KEY, JSON.stringify(marks)); return true; }
    catch (err) { console.warn("儲存熟練度標記失敗:", err); return false; }
}

// 間隔複習：標記日期 d ＋ 間隔天數 = 下次複習日。熟練的間隔依 n（連續答熟練次數）逐級拉長。
const QM_INTERVALS = { weak: [1], review: [3], done: [7, 14, 30, 60, 120] };

function qmToday() {  // 本地日期（toISOString 是 UTC，台灣早上 8 點前會變成昨天）
    const t = new Date();
    return t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-" + String(t.getDate()).padStart(2, "0");
}

function qmDue(m) {
    if (!m.d) return qmToday();  // 舊資料沒有日期：視為今天到期
    const steps = QM_INTERVALS[m.s] || [1];
    const days = steps[Math.min(m.n || 0, steps.length - 1)];
    const [y, mo, d] = m.d.split("-").map(Number);
    const due = new Date(y, mo - 1, d + days);
    return due.getFullYear() + "-" + String(due.getMonth() + 1).padStart(2, "0") + "-" + String(due.getDate()).padStart(2, "0");
}

function qmIsDue(m) { return qmDue(m) <= qmToday(); }

// 設定標記；同狀態且已到期 → 算一次複習（熟練升一級），同狀態未到期 → 取消（原本的行為）
function qmSet(all, key, s, info) {
    const old = all[key];
    if (old && old.s === s && !qmIsDue(old)) { delete all[key]; return "cleared"; }
    const n = old && old.s === "done" && s === "done" ? (old.n || 0) + 1 : 0;
    all[key] = { s, t: info.t || (old && old.t), h: info.h || (old && old.h), d: qmToday(), n };
    return "set";
}

function initQuestionMarks() {
    const items = document.querySelectorAll(".qb-item[data-q]");
    if (!items.length) return;
    const marks = qmLoad();
    items.forEach(item => {
        const meta = item.querySelector(".qb-meta");
        if (!meta || meta.querySelector(".qm-group")) return;
        const key = item.dataset.q;
        const group = document.createElement("span");
        group.className = "qm-group";
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", "熟練度");
        const dueBadge = document.createElement("span");
        dueBadge.className = "pb-count qm-due";
        dueBadge.textContent = "該複習";
        dueBadge.title = "已到複習日：自己作答後，再按一次目前的狀態（或改成別的）記錄這次複習";
        const render = () => {
            const m = qmLoad()[key];
            const s = (m || {}).s || "";
            item.dataset.qm = s;
            group.querySelectorAll("button").forEach(b => {
                b.setAttribute("aria-pressed", String(b.dataset.s === s));
                b.title = b.dataset.s === s && m ? "下次複習 " + qmDue(m) + (qmIsDue(m) ? "（已到期，按一下記錄複習）" : "（再按一次取消）") : "";
            });
            if (m && qmIsDue(m)) group.prepend(dueBadge); else dueBadge.remove();
        };
        QM_STATES.forEach(([s, label]) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "qm-btn qm-btn--" + s;
            b.dataset.s = s;
            b.textContent = label;
            b.onclick = () => {
                const all = qmLoad();
                qmSet(all, key, s, { t: item.dataset.label, h: item.dataset.href });
                if (!qmSave(all)) { alert("無法儲存標記（瀏覽器可能停用了本機儲存空間）"); return; }
                // 同一頁可能出現同一題兩次（跨科考卷），一起更新
                document.querySelectorAll(`.qb-item[data-q="${key}"]`).forEach(el => el.dispatchEvent(new Event("qm-sync")));
                document.dispatchEvent(new Event("qm-change"));  // 篩選列更新計數
            };
            group.appendChild(b);
        });
        item.addEventListener("qm-sync", render);
        meta.appendChild(group);
        if (marks[key]) render();
    });
}

// 我的複習清單頁（#qm-review）：匯出／匯入工具列＋依狀態列出標記過的題目
function initReviewList() {
    const box = document.getElementById("qm-review");
    if (!box || box.dataset.ready) return;
    box.dataset.ready = "1";
    const list = document.createElement("div");
    box.replaceChildren(qmToolbar(() => qmRenderList(list)), list);
    qmRenderList(list);
}

// 匯出成 JSON 檔備份、從檔案匯入（換裝置、換瀏覽器時搬移標記）
const QM_FILE_TYPE = "landnote-qmark";

function qmToolbar(onChange) {
    const bar = document.createElement("div");
    bar.className = "qm-toolbar";
    bar.style.cssText = "display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;margin:0 0 1rem;";
    const msg = document.createElement("p");
    msg.setAttribute("role", "status");
    msg.style.cssText = "flex-basis:100%;margin:0;font-size:0.8em;";

    const exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "md-button";
    exportBtn.textContent = "匯出標記";
    exportBtn.onclick = () => {
        const marks = qmLoad();
        const n = Object.keys(marks).length;
        if (!n) { msg.textContent = "還沒有標記可以匯出。"; return; }
        const today = new Date().toISOString().slice(0, 10);
        const data = { type: QM_FILE_TYPE, version: 1, exported: today, marks };
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = "landnote-標記-" + today + ".json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        msg.textContent = "已匯出 " + n + " 題標記。到另一台裝置的這一頁按「匯入標記」選這個檔案即可。";
    };

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json,.json";
    input.hidden = true;
    input.onchange = async () => {
        const file = input.files && input.files[0];
        input.value = "";  // 同一個檔案可再選一次
        if (!file) return;
        try {
            const result = qmMerge(JSON.parse(await file.text()));
            msg.textContent = "匯入完成：新增 " + result.added + " 題、更新 " + result.updated + " 題" +
                (result.kept ? "、保留本機較新的 " + result.kept + " 題" : "") +
                (result.skipped ? "，略過 " + result.skipped + " 筆格式不符的資料" : "") + "。";
            onChange();
        } catch (err) {
            console.error("匯入標記失敗:", err);
            msg.textContent = "匯入失敗：" + err.message;
        }
    };
    const importBtn = document.createElement("button");
    importBtn.type = "button";
    importBtn.className = "md-button";
    importBtn.textContent = "匯入標記";
    importBtn.onclick = () => input.click();

    bar.append(exportBtn, importBtn, input, msg);
    return bar;
}

// 合併匯入的標記：本機沒有的直接加入；兩邊都有時保留標記日期較新的（同一天以匯入檔為準）
function qmMerge(data) {
    if (!data || data.type !== QM_FILE_TYPE || typeof data.marks !== "object" || data.marks === null) {
        throw new Error("不是 Landnote 匯出的標記檔");
    }
    const states = new Set(QM_STATES.map(([s]) => s));
    const all = qmLoad();
    const result = { added: 0, updated: 0, kept: 0, skipped: 0 };
    Object.entries(data.marks).forEach(([key, m]) => {
        // data-href 是站內相對路徑；擋掉 javascript: 等任何帶協定的網址
        const valid = /^[\w-]+$/.test(key) && m && states.has(m.s) &&
            (m.h === undefined || (typeof m.h === "string" && /^[\w\-./#]*$/.test(m.h))) &&
            (m.t === undefined || typeof m.t === "string") &&
            (m.d === undefined || (typeof m.d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(m.d))) &&
            (m.n === undefined || (Number.isInteger(m.n) && m.n >= 0 && m.n < 100));
        if (!valid) { result.skipped++; return; }
        const mark = { s: m.s, t: m.t, h: m.h, d: m.d, n: m.n || 0 };
        const local = all[key];
        if (!local) { all[key] = mark; result.added++; }
        else if ((mark.d || "") >= (local.d || "")) { all[key] = mark; result.updated++; }
        else result.kept++;
    });
    if (!qmSave(all)) throw new Error("瀏覽器無法儲存（可能停用了本機儲存空間）");
    return result;
}

function qmRenderList(box) {
    const marks = qmLoad();
    const keys = Object.keys(marks);
    box.replaceChildren();
    if (!keys.length) {
        box.innerHTML = "<p>還沒有標記任何題目。到各科題目頁或連續刷題頁，按題目上方的按鈕開始標記。</p>";
        return;
    }
    const summary = document.createElement("p");
    summary.textContent = "共標記 " + keys.length + " 題：" +
        QM_STATES.map(([s, label]) => label + " " + keys.filter(k => marks[k].s === s).length).join("・");
    box.appendChild(summary);
    // 頁面在 exam-reader/review/，data-href 相對 exam-reader/
    const base = new URL("../", window.location.href);

    // 今天該複習：到期的題目，舊的先；點題目去作答，回來直接在這裡按結果
    const due = keys.filter(k => qmIsDue(marks[k])).sort((a, b) => qmDue(marks[a]).localeCompare(qmDue(marks[b])));
    const dh = document.createElement("h2");
    dh.textContent = "今天該複習（" + due.length + "）";
    box.appendChild(dh);
    if (!due.length) {
        const next = keys.map(k => qmDue(marks[k])).sort()[0];
        const p = document.createElement("p");
        p.textContent = "今天沒有到期的題目。" + (next ? "下一批在 " + next + "。" : "");
        box.appendChild(p);
    } else {
        const p = document.createElement("p");
        p.textContent = "點題目回原題先自己作答，再回來按這次的結果：不熟明天再看、待複習 3 天後、熟練則間隔逐次拉長（7→14→30→60→120 天）。";
        const ul = document.createElement("ul");
        ul.className = "qm-list qm-due-list";
        due.forEach(k => {
            const li = document.createElement("li");
            const a = document.createElement("a");
            a.href = new URL(marks[k].h || "", base).href;
            a.textContent = marks[k].t || k;
            const meta = document.createElement("span");
            meta.className = "qm-date";
            meta.textContent = "上次：" + (QM_STATES.find(([s]) => s === marks[k].s) || ["", ""])[1] + (marks[k].d ? " " + marks[k].d : "");
            const group = document.createElement("span");
            group.className = "qm-group";
            QM_STATES.forEach(([s, label]) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "qm-btn qm-btn--" + s;
                b.textContent = label;
                b.onclick = () => {
                    const all = qmLoad();
                    if (!all[k]) return;
                    qmSet(all, k, s, {});
                    if (qmSave(all)) qmRenderList(box);
                };
                group.appendChild(b);
            });
            li.append(a, " ", meta, " ", group);
            ul.appendChild(li);
        });
        box.append(p, ul);
    }

    QM_STATES.forEach(([s, label]) => {
        const rows = keys.filter(k => marks[k].s === s)
            .sort((a, b) => (marks[b].d || "").localeCompare(marks[a].d || "") || (marks[a].t || "").localeCompare(marks[b].t || ""));
        if (!rows.length) return;
        const h = document.createElement("h2");
        h.textContent = label + "（" + rows.length + "）";
        const ul = document.createElement("ul");
        ul.className = "qm-list";
        rows.forEach(k => {
            const li = document.createElement("li");
            const a = document.createElement("a");
            a.href = new URL(marks[k].h || "", base).href;
            a.textContent = marks[k].t || k;
            const date = document.createElement("span");
            date.className = "qm-date";
            date.textContent = (marks[k].d ? "標記於 " + marks[k].d + "・" : "") + "下次複習 " + qmDue(marks[k]);
            const rm = document.createElement("button");
            rm.type = "button";
            rm.className = "qm-btn";
            rm.textContent = "移除";
            rm.onclick = () => {
                const all = qmLoad();
                delete all[k];
                if (qmSave(all)) qmRenderList(box);  // 重繪，統計數字一起更新
            };
            li.append(a, " ", date, " ", rm);
            ul.appendChild(li);
        });
        box.append(h, ul);
    });
}

// 題目篩選列：只看不熟／該複習／待複習／未標記的題目（考卷頁、連續刷題頁、比較頁皆適用）。
// 不記住選擇，避免下次進來只剩幾題卻不知道為什麼；改標記時只更新計數，題目要再按一次篩選才隱藏，免得一按就消失。
const QM_FILTERS = [
    ["all", "全部", () => true],
    ["weak", "不熟", m => m && m.s === "weak"],
    ["due", "該複習", m => m && qmIsDue(m)],
    ["review", "待複習", m => m && m.s === "review"],
    ["none", "未標記", m => !m],
];

function initMarkFilter() {
    const article = document.querySelector("article.md-content__inner");
    if (!article || article.querySelector(".qm-filter")) return;
    const items = [...article.querySelectorAll(".qb-item[data-q]")];
    if (items.length < 5) return;
    const bar = document.createElement("div");
    bar.className = "qm-filter";
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "依熟練度篩選題目");
    const status = document.createElement("p");
    status.className = "qm-filter-status";
    status.setAttribute("role", "status");
    let current = "all";

    const count = () => {
        const marks = qmLoad();
        bar.querySelectorAll("button").forEach(b => {
            const test = QM_FILTERS.find(f => f[0] === b.dataset.f)[2];
            b.querySelector("span").textContent = items.filter(el => test(marks[el.dataset.q])).length;
        });
    };
    const apply = () => {
        const marks = qmLoad();
        const test = QM_FILTERS.find(f => f[0] === current)[2];
        let shown = 0;
        items.forEach(el => {
            const ok = test(marks[el.dataset.q]);
            el.hidden = !ok;
            const src = el.previousElementSibling;  // 連續刷題頁每題上方的出處列
            if (src && src.classList.contains("er-drill-src")) src.hidden = !ok;
            if (ok) shown++;
        });
        // 區段標題（年度、申論／測驗）底下沒有可見題目就一起藏
        article.querySelectorAll("h2").forEach(h => {
            let el = h.nextElementSibling, has = false, any = false;
            while (el && el.tagName !== "H2") {
                if (el.matches(".qb-item[data-q]")) { any = true; if (!el.hidden) has = true; }
                el = el.nextElementSibling;
            }
            if (any) h.hidden = !has;
        });
        bar.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.f === current)));
        status.textContent = current === "all" ? "" :
            shown ? "顯示 " + shown + "／" + items.length + " 題" : "這一頁沒有符合的題目。";
        count();
    };
    QM_FILTERS.forEach(([f, label]) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "qm-btn qm-filter-btn";
        b.dataset.f = f;
        b.append(label + " ", document.createElement("span"));
        b.onclick = () => { current = f; apply(); };
        bar.appendChild(b);
    });
    const anchor = article.querySelector(".er-drill-toggle") || article.querySelector(".qm-reminder") ||
        article.querySelector("h1 ~ .qb-meta") || article.querySelector("h1");
    (anchor || article.firstChild).after(bar, status);
    // instant navigation 換頁不重載，先移除上一頁的監聽
    if (window.qmFilterCount) document.removeEventListener("qm-change", window.qmFilterCount);
    window.qmFilterCount = count;
    document.addEventListener("qm-change", count);
    apply();
}

// ---- 刷題計畫與隨機抽題（exam-reader/practice/ 的 #qm-practice）----
// 題目索引 exam-reader/questions.json 由 exam_reader._write_question_index 產生；題目卡從各考卷頁抓來就地顯示。
const QM_PLAN_KEY = "qm_plan_v1";    // {exam, fams, kind, answered, src, n}
const QM_TODAY_KEY = "qm_today_v1";  // {date, keys}：當天的題目固定，標記後重整也不會換題
const QM_REVIEW_ONLY_DAYS = 7;       // 考前最後一週只複習不加新題
const QM_NEW_MAX = 40;

function qmStore(key, value) {
    try {
        if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
        localStorage.setItem(key, JSON.stringify(value));
    } catch (err) { console.warn("本機儲存失敗:", key, err); }
    return null;
}

function qmSeeded(seed) {  // 依日期字串產生固定亂數（同一天排出同樣的新題）
    let h = 2166136261;
    for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return () => { h = Math.imul(h ^ (h >>> 15), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); return ((h ^= h >>> 16) >>> 0) / 4294967296; };
}

function qmShuffle(arr, rand) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
}

function qmDaysUntil(dateStr) {
    const [y, m, d] = dateStr.split("-").map(Number);
    const t = new Date(); t.setHours(0, 0, 0, 0);
    return Math.round((new Date(y, m - 1, d) - t) / 86400000);
}

async function initPractice() {
    const box = document.getElementById("qm-practice");
    if (!box || box.dataset.ready) return;
    box.dataset.ready = "1";
    const root = new URL("../", window.location.href);  // exam-reader/
    let index;
    try {
        const res = await fetch(new URL("questions.json", root));
        if (!res.ok) throw new Error("HTTP " + res.status);
        index = await res.json();
    } catch (err) {
        console.error("題目索引載入失敗:", err);
        box.innerHTML = "<p>題目索引載入失敗，請重新整理頁面。</p>";
        return;
    }
    const all = [];
    index.families.forEach(f => f.papers.forEach(([pid, year, qids]) => qids.forEach(raw => {
        const q = raw.replace("*", "");
        all.push({ key: pid + "-" + q, slug: f.slug, pid, q, year, kind: q[0], ans: raw.endsWith("*") });
    })));
    const byKey = new Map(all.map(x => [x.key, x]));
    const plan = Object.assign({ exam: "", fams: [], kind: "all", answered: true, src: "all", n: 10 }, qmStore(QM_PLAN_KEY) || {});
    const save = () => qmStore(QM_PLAN_KEY, plan);
    const inScope = x => (!plan.fams.length || plan.fams.includes(x.slug)) &&
        (plan.kind === "all" || x.kind === plan.kind) && (!plan.answered || x.ans);

    const el = (tag, attrs = {}, ...kids) => {
        const e = document.createElement(tag);
        Object.entries(attrs).forEach(([k, v]) => { if (k === "class") e.className = v; else if (k in e) e[k] = v; else e.setAttribute(k, v); });
        e.append(...kids);
        return e;
    };

    // 範圍設定
    const famBox = el("div", { class: "qm-practice-fams" });
    index.families.forEach(f => {
        const n = all.filter(x => x.slug === f.slug).length;
        const cb = el("input", { type: "checkbox", checked: plan.fams.includes(f.slug) });
        cb.onchange = () => { plan.fams = cb.checked ? [...plan.fams, f.slug] : plan.fams.filter(s => s !== f.slug); save(); refresh(); };
        famBox.append(el("label", {}, cb, " " + f.name + "（" + n + "）"));
    });
    const kindSel = el("select", {}, ...[["all", "申論＋測驗"], ["e", "只要申論"], ["c", "只要測驗"]].map(([v, t]) => el("option", { value: v }, t)));
    kindSel.value = plan.kind;
    kindSel.onchange = () => { plan.kind = kindSel.value; save(); refresh(); };
    const ansCb = el("input", { type: "checkbox", checked: plan.answered });
    ansCb.onchange = () => { plan.answered = ansCb.checked; save(); refresh(); };
    const scopeInfo = el("p", { class: "qm-date" });

    // 考前計畫
    const dateIn = el("input", { type: "date", value: plan.exam });
    dateIn.onchange = () => { plan.exam = dateIn.value; save(); refresh(); };
    const planInfo = el("p");
    const todayBtn = el("button", { type: "button", class: "md-button md-button--primary" }, "開始今天的題目");
    const redoBtn = el("button", { type: "button", class: "md-button" }, "重新排今天");

    // 隨機抽題
    const srcSel = el("select", {}, ...QM_FILTERS.map(([v, t]) => el("option", { value: v }, v === "all" ? "全部題目" : "只抽" + t)));
    srcSel.value = plan.src;
    srcSel.onchange = () => { plan.src = srcSel.value; save(); refresh(); };
    const nSel = el("select", {}, ...[5, 10, 20, 30].map(v => el("option", { value: v }, v + " 題")));
    nSel.value = String(plan.n);
    nSel.onchange = () => { plan.n = Number(nSel.value); save(); };
    const drawBtn = el("button", { type: "button", class: "md-button md-button--primary" }, "抽題");
    const drawInfo = el("p", { class: "qm-date" });

    const out = el("div", { class: "qm-practice-out" });

    const todayPlan = (force) => {
        const today = qmToday();
        const saved = qmStore(QM_TODAY_KEY);
        if (!force && saved && saved.date === today) return saved.keys.filter(k => byKey.has(k));
        const marks = qmLoad();
        const scope = all.filter(inScope);
        const due = scope.filter(x => marks[x.key] && qmIsDue(marks[x.key]))
            .sort((a, b) => qmDue(marks[a.key]).localeCompare(qmDue(marks[b.key])));
        const fresh = scope.filter(x => !marks[x.key]);
        const days = plan.exam ? qmDaysUntil(plan.exam) : null;
        const quota = days === null ? 10 : days > QM_REVIEW_ONLY_DAYS ? Math.min(QM_NEW_MAX, Math.ceil(fresh.length / (days - QM_REVIEW_ONLY_DAYS))) : 0;
        // 新題：近 5 年的優先（最貼近現在的出題方向），同一天順序固定
        const maxYear = Math.max(...scope.map(x => x.year));
        const rand = qmSeeded(today);
        const recent = qmShuffle(fresh.filter(x => x.year > maxYear - 5), rand);
        const older = qmShuffle(fresh.filter(x => x.year <= maxYear - 5), rand);
        const keys = [...due.map(x => x.key), ...recent.concat(older).slice(0, quota).map(x => x.key)];
        qmStore(QM_TODAY_KEY, { date: today, keys });
        return keys;
    };

    function refresh() {
        const marks = qmLoad();
        const scope = all.filter(inScope);
        const fresh = scope.filter(x => !marks[x.key]).length;
        const due = scope.filter(x => marks[x.key] && qmIsDue(marks[x.key])).length;
        scopeInfo.textContent = "範圍內 " + scope.length + " 題：未作答 " + fresh + "、今天到期 " + due + "（沒勾科目＝全部科目）";
        if (!plan.exam) {
            planInfo.textContent = "設定考試日期後，會依剩餘天數平均分配新題；沒設定則每天 10 題新題＋到期複習。";
        } else {
            const days = qmDaysUntil(plan.exam);
            if (days < 0) planInfo.textContent = "考試日期已過，請重新設定。";
            else {
                const quota = days > QM_REVIEW_ONLY_DAYS ? Math.min(QM_NEW_MAX, Math.ceil(fresh / (days - QM_REVIEW_ONLY_DAYS))) : 0;
                planInfo.textContent = "距離考試 " + days + " 天。今天：到期複習 " + due + " 題＋新題 " + quota + " 題" +
                    (days <= QM_REVIEW_ONLY_DAYS ? "（最後一週只複習）" : "") +
                    (quota >= QM_NEW_MAX && fresh / QM_NEW_MAX > days - QM_REVIEW_ONLY_DAYS ? "。題目做不完，建議縮小範圍或只選測驗題。" : "。");
            }
        }
        const test = QM_FILTERS.find(f => f[0] === plan.src)[2];
        drawInfo.textContent = "可抽 " + scope.filter(x => test(marks[x.key])).length + " 題";
    }

    const pages = new Map();  // 考卷頁網址 → Promise<Document>
    const fetchPage = url => {
        if (!pages.has(url)) {
            pages.set(url, fetch(url).then(r => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.text();
            }).then(t => new DOMParser().parseFromString(t, "text/html")));
        }
        return pages.get(url);
    };

    async function show(keys, title) {
        out.replaceChildren(el("h2", {}, title));
        if (!keys.length) { out.append(el("p", {}, "沒有符合的題目，調整範圍或來源再試一次。")); return; }
        const status = el("p", { class: "qm-date", role: "status" }, "載入題目中…");
        const list = el("div");
        out.append(status, list);
        const slots = keys.map(() => list.appendChild(el("div")));
        let done = 0;
        await Promise.all(keys.map(async (key, i) => {
            const x = byKey.get(key);
            const url = new URL(x.slug + "/" + x.pid + "/", root).href;
            try {
                const doc = await fetchPage(url);
                const card = doc.getElementById(x.q);
                if (!card) throw new Error("找不到題目 " + x.q);
                const node = document.importNode(card, true);
                node.id = "p-" + key;
                node.querySelectorAll(".qm-group").forEach(g => g.remove());
                node.querySelectorAll("[href]").forEach(a => {
                    const v = a.getAttribute("href");
                    if (v && !v.startsWith("#")) a.setAttribute("href", new URL(v, url).href);
                });
                node.querySelectorAll("[src]").forEach(a => a.setAttribute("src", new URL(a.getAttribute("src"), url).href));
                const head = el("p", { class: "er-drill-src" },
                    el("a", { href: url + "#" + x.q }, (i + 1) + ". " + (node.dataset.label || key)));
                slots[i].replaceChildren(head, node);
            } catch (err) {
                console.error("題目載入失敗:", key, err);
                slots[i].replaceChildren(el("p", {}, "第 " + (i + 1) + " 題載入失敗，", el("a", { href: url + "#" + x.q }, "到原考卷看"), "。"));
            }
            status.textContent = "已載入 " + (++done) + "／" + keys.length + " 題";
        }));
        status.textContent = "共 " + keys.length + " 題。作答後按題目上的不熟／待複習／熟練，排進間隔複習。";
        initQuestionMarks();
    }

    todayBtn.onclick = () => show(todayPlan(false), "今天的題目（" + qmToday() + "）");
    redoBtn.onclick = () => { if (confirm("依目前範圍重新排今天的題目？")) show(todayPlan(true), "今天的題目（" + qmToday() + "）"); };
    drawBtn.onclick = () => {
        const marks = qmLoad();
        const test = QM_FILTERS.find(f => f[0] === plan.src)[2];
        const pool = all.filter(x => inScope(x) && test(marks[x.key]));
        show(qmShuffle(pool, Math.random).slice(0, plan.n).map(x => x.key),
            "隨機抽題（" + Math.min(plan.n, pool.length) + "／" + pool.length + " 題）");
    };

    box.replaceChildren(
        el("h2", {}, "範圍"), famBox,
        el("p", { class: "qm-practice-row" }, "題型 ", kindSel, " ", el("label", {}, ansCb, " 只要有解答的題目")),
        scopeInfo,
        el("h2", {}, "考前計畫"),
        el("p", { class: "qm-practice-row" }, "考試日期 ", dateIn), planInfo,
        el("p", { class: "qm-practice-row" }, todayBtn, " ", redoBtn),
        el("h2", {}, "隨機抽題"),
        el("p", { class: "qm-practice-row" }, srcSel, " ", nSel, " ", drawBtn), drawInfo,
        out);
    if (window.qmPracticeRefresh) document.removeEventListener("qm-change", window.qmPracticeRefresh);
    window.qmPracticeRefresh = refresh;
    document.addEventListener("qm-change", refresh);
    refresh();
}

// 逐題讀各頁（複習清單頁除外）標題下提醒今天有幾題到期
function initDueReminder() {
    const path = window.location.pathname;
    const at = path.indexOf("/exam-reader/");
    const h1 = document.querySelector(".md-content__inner h1");
    if (at < 0 || !h1 || document.getElementById("qm-review") || document.querySelector(".qm-reminder")) return;
    const marks = qmLoad();
    const n = Object.values(marks).filter(m => m && qmIsDue(m)).length;
    if (!n) return;
    const p = document.createElement("p");
    p.className = "qm-reminder";
    const a = document.createElement("a");
    a.href = path.slice(0, at) + "/exam-reader/review/";
    a.textContent = "今天有 " + n + " 題該複習 →";
    p.appendChild(a);
    h1.insertAdjacentElement("afterend", p);
}

// 監聽 MkDocs Material 的單頁式導航事件 (instant navigation)
if (typeof document$ !== "undefined") {
    document$.subscribe(function () {
        initStudyTools();
        initInfiniteBlog();
        initDrillToggle();
        initQuestionMarks();
        initReviewList();
        initDueReminder();
        initMarkFilter();
        initPractice();
    });
} else {
    document.addEventListener("DOMContentLoaded", function () {
        initStudyTools();
        initInfiniteBlog();
        initDrillToggle();
        initQuestionMarks();
        initReviewList();
        initDueReminder();
        initMarkFilter();
        initPractice();
    });
}
