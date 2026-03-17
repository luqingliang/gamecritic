const RECENT_GAMES_KEY = "gamecritic_recent_games";
const LANGUAGE_KEY = "gamecritic_lang";
const INITIAL_VISIBLE_REVIEWS = 20;
const REVIEW_INCREMENT = 20;

const COPY = {
  zh: {
    htmlLang: "zh-CN",
    pageTitle: "Gamecritic",
    languageGroupLabel: "语言切换",
    introHint: "输入游戏名后开始检索，高置信结果会直接打开详情页。",
    inputPlaceholder: "例如：Elden Ring",
    submitIdle: "检索",
    submitLoading: "检索中...",
    recentTitle: "最近访问",
    clearRecent: "清空",
    recentEmpty: "还没有最近访问记录。",
    searchTitle: "搜索结果",
    searchMeta: ({ shown, total }) => (
      total > shown
        ? `共 ${total} 个候选，当前展示前 ${shown} 个`
        : `共 ${shown} 个候选`
    ),
    searchLoadingTitle: "正在加载游戏信息",
    emptyTitle: "从一个游戏名开始",
    emptyCopy: "输入游戏名，系统会先从本地索引匹配最接近的游戏，再获取基础信息和评论数据。",
    noCover: "暂无封面",
    profileKicker: "游戏档案",
    dataSourceCached: "命中本地缓存",
    dataSourceAutoCrawled: "本次请求触发抓取",
    labelPlatform: "平台",
    labelRelease: "发售时间",
    labelRating: "评级",
    labelScrapedAt: "抓取时间",
    criticScoreLabel: "媒体评分",
    userScoreLabel: "用户评分",
    reviewsTitle: "评论视图",
    reviewSummaryLoading: "正在加载评论数据...",
    reviewSummaryCounts: ({ criticCount, userCount }) => `媒体 ${criticCount} 条 · 用户 ${userCount} 条`,
    reviewTabsLabel: "评论类型",
    tabCritic: "媒体评论",
    tabUser: "用户评论",
    criticMore: "加载更多媒体评论",
    userMore: "加载更多用户评论",
    technicalSummary: "技术信息",
    techSlug: "slug",
    techSource: "数据来源",
    techCriticTotal: "媒体评论数量",
    techUserTotal: "用户评论数量",
    techSourceCached: "直接读取现有数据库",
    techSourceAutoCrawled: "接口触发抓取后落库",
    reviewCount: ({ count }) => `${count} 条评论`,
    unknownCritic: "未知媒体",
    unknownPlayer: "未知玩家",
    missingQuote: "该评论没有摘要文本。",
    noCriticReviews: "当前没有媒体评论数据。",
    noUserReviews: "当前没有用户评论数据。",
    unnamedGame: "未命名游戏",
    errorInvalidSearch: "请输入一个有效的游戏名。",
    errorInvalidRoute: "无法识别当前游戏地址。",
    errorResponseParse: "响应解析失败",
    errorRequestFailed: ({ status }) => `请求失败: ${status}`,
    errorNoMatch: ({ query }) => (
      `<strong>没有找到匹配结果。</strong><br>当前本地索引里没有与 <strong>${escapeHtml(query)}</strong> 接近的游戏。`
    ),
    errorSearchFailed: ({ error }) => `<strong>搜索失败。</strong><br>${escapeHtml(error)}`,
    errorLookupFailed: ({ error }) => `<strong>检索失败。</strong><br>${escapeHtml(error)}`,
  },
  en: {
    htmlLang: "en",
    pageTitle: "Gamecritic",
    languageGroupLabel: "Language switch",
    introHint: "Enter a game title to search. High-confidence matches open the detail page directly.",
    inputPlaceholder: "For example: Elden Ring",
    submitIdle: "Search",
    submitLoading: "Searching...",
    recentTitle: "Recent",
    clearRecent: "Clear",
    recentEmpty: "No recent games yet.",
    searchTitle: "Results",
    searchMeta: ({ shown, total }) => (
      total > shown
        ? `${shown} of ${total} matches shown`
        : `${shown} match${shown === 1 ? "" : "es"}`
    ),
    searchLoadingTitle: "Loading game details",
    emptyTitle: "Start with a game title",
    emptyCopy: "Enter a game title to match against the local index, then load the game profile and reviews.",
    noCover: "NO COVER",
    profileKicker: "GAME PROFILE",
    dataSourceCached: "Local cache",
    dataSourceAutoCrawled: "Fetched on demand",
    labelPlatform: "Platform",
    labelRelease: "Release date",
    labelRating: "Rating",
    labelScrapedAt: "Scraped at",
    criticScoreLabel: "Critic score",
    userScoreLabel: "User score",
    reviewsTitle: "Reviews",
    reviewSummaryLoading: "Loading reviews...",
    reviewSummaryCounts: ({ criticCount, userCount }) => `Critic ${criticCount} · User ${userCount}`,
    reviewTabsLabel: "Review type",
    tabCritic: "Critic reviews",
    tabUser: "User reviews",
    criticMore: "Load more critic reviews",
    userMore: "Load more user reviews",
    technicalSummary: "Technical info",
    techSlug: "Slug",
    techSource: "Data source",
    techCriticTotal: "Critic review count",
    techUserTotal: "User review count",
    techSourceCached: "Read directly from the local database",
    techSourceAutoCrawled: "Fetched and stored by the API request",
    reviewCount: ({ count }) => `${count} review${count === 1 ? "" : "s"}`,
    unknownCritic: "Unknown critic",
    unknownPlayer: "Unknown player",
    missingQuote: "This review has no quote excerpt.",
    noCriticReviews: "No critic reviews are available for this game yet.",
    noUserReviews: "No user reviews are available for this game yet.",
    unnamedGame: "Untitled game",
    errorInvalidSearch: "Enter a valid game title.",
    errorInvalidRoute: "The current game route could not be resolved.",
    errorResponseParse: "Failed to parse the response.",
    errorRequestFailed: ({ status }) => `Request failed: ${status}`,
    errorNoMatch: ({ query }) => (
      `<strong>No matches found.</strong><br>The local index has nothing close to <strong>${escapeHtml(query)}</strong>.`
    ),
    errorSearchFailed: ({ error }) => `<strong>Search failed.</strong><br>${escapeHtml(error)}`,
    errorLookupFailed: ({ error }) => `<strong>Lookup failed.</strong><br>${escapeHtml(error)}`,
  },
};

const state = {
  locale: loadSavedLocale(),
  slug: "",
  game: null,
  search: { query: "", matches: [], total_matches: 0, selected: null, status: "idle" },
  reviews: { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } },
  activeTab: "critic",
  visibleCritic: INITIAL_VISIBLE_REVIEWS,
  visibleUser: INITIAL_VISIBLE_REVIEWS,
  gameLoading: false,
  reviewsLoading: false,
  isBusy: false,
  gameError: "",
  reviewsError: "",
  status: null,
  requestId: 0,
};

const elements = {
  pageTitle: document.getElementById("page-title"),
  langSwitch: document.getElementById("lang-switch"),
  langZh: document.getElementById("lang-zh"),
  langEn: document.getElementById("lang-en"),
  form: document.getElementById("slug-form"),
  intro: document.getElementById("lookup-intro"),
  input: document.getElementById("slug-input"),
  submitButton: document.getElementById("submit-button"),
  recentTitle: document.getElementById("recent-title"),
  searchPanel: document.getElementById("search-panel"),
  searchTitle: document.getElementById("search-title"),
  searchMeta: document.getElementById("search-meta"),
  searchResults: document.getElementById("search-results"),
  recentList: document.getElementById("recent-list"),
  clearRecent: document.getElementById("clear-recent"),
  emptyState: document.getElementById("empty-state"),
  emptyTitle: document.getElementById("empty-title"),
  emptyCopy: document.getElementById("empty-copy"),
  results: document.getElementById("results"),
  statusCard: document.getElementById("status-card"),
  coverImage: document.getElementById("cover-image"),
  coverPlaceholder: document.getElementById("cover-placeholder"),
  profileKicker: document.getElementById("profile-kicker"),
  gameTitle: document.getElementById("game-title"),
  gamePlatform: document.getElementById("game-platform"),
  gameRelease: document.getElementById("game-release"),
  gameRating: document.getElementById("game-rating"),
  gameScrapedAt: document.getElementById("game-scraped-at"),
  dataSourceBadge: document.getElementById("data-source-badge"),
  labelPlatform: document.getElementById("label-platform"),
  labelRelease: document.getElementById("label-release"),
  labelRating: document.getElementById("label-rating"),
  labelScrapedAt: document.getElementById("label-scraped-at"),
  criticScoreLabel: document.getElementById("critic-score-label"),
  criticScore: document.getElementById("critic-score"),
  criticCount: document.getElementById("critic-count"),
  userScoreLabel: document.getElementById("user-score-label"),
  userScore: document.getElementById("user-score"),
  userCount: document.getElementById("user-count"),
  reviewsTitle: document.getElementById("reviews-title"),
  reviewSummary: document.getElementById("review-summary"),
  reviewTabBar: document.getElementById("review-tab-bar"),
  tabCritic: document.getElementById("tab-critic"),
  tabUser: document.getElementById("tab-user"),
  criticPanel: document.getElementById("critic-panel"),
  userPanel: document.getElementById("user-panel"),
  criticMore: document.getElementById("critic-more"),
  userMore: document.getElementById("user-more"),
  technicalSummary: document.getElementById("technical-summary"),
  techSlug: document.getElementById("tech-slug"),
  techSource: document.getElementById("tech-source"),
  techCriticTotal: document.getElementById("tech-critic-total"),
  techUserTotal: document.getElementById("tech-user-total"),
  labelTechSlug: document.getElementById("label-tech-slug"),
  labelTechSource: document.getElementById("label-tech-source"),
  labelTechCriticTotal: document.getElementById("label-tech-critic-total"),
  labelTechUserTotal: document.getElementById("label-tech-user-total"),
};

function loadSavedLocale() {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY);
    if (saved === "en" || saved === "zh") {
      return saved;
    }
  } catch {
    return "zh";
  }
  return "zh";
}

function saveLocale(locale) {
  try {
    localStorage.setItem(LANGUAGE_KEY, locale);
  } catch {
    return;
  }
}

function messages() {
  return COPY[state.locale] || COPY.zh;
}

function t(key, params = {}) {
  const value = messages()[key];
  if (typeof value === "function") {
    return value(params);
  }
  return value;
}

function normalizeSlug(value) {
  return String(value || "").trim();
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString(state.locale === "en" ? "en-US" : "zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scoreText(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function countText(value) {
  const numeric = Number(value || 0);
  return t("reviewCount", { count: numeric });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function getRecentGames() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_GAMES_KEY) || "[]");
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item) => (
      item
      && typeof item === "object"
      && typeof item.slug === "string"
      && item.slug.trim()
      && typeof item.title === "string"
      && item.title.trim()
    ));
  } catch {
    return [];
  }
}

function saveRecentGame(game) {
  const slug = normalizeSlug(game && game.slug);
  const title = normalizeSlug(game && game.title);
  if (!slug || !title) {
    return;
  }
  const next = [
    { slug, title },
    ...getRecentGames().filter((item) => item.slug !== slug),
  ].slice(0, 8);
  localStorage.setItem(RECENT_GAMES_KEY, JSON.stringify(next));
  renderRecentGames();
}

function clearRecentGames() {
  localStorage.removeItem(RECENT_GAMES_KEY);
  renderRecentGames();
}

function renderRecentGames() {
  const recent = getRecentGames();
  if (recent.length === 0) {
    elements.recentList.classList.add("empty");
    elements.recentList.textContent = t("recentEmpty");
    return;
  }

  elements.recentList.classList.remove("empty");
  elements.recentList.innerHTML = recent
    .map((item) => (
      `<button class="recent-chip" type="button" data-slug="${escapeHtml(item.slug)}">${escapeHtml(item.title)}</button>`
    ))
    .join("");
}

function resetSearchState() {
  state.search = { query: "", matches: [], total_matches: 0, selected: null, status: "idle" };
}

function releaseDateTimestamp(value) {
  const normalized = String(value || "").trim();
  if (!normalized || normalized === "-") {
    return Number.NEGATIVE_INFINITY;
  }
  const timestamp = Date.parse(normalized);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function compareSearchMatches(left, right) {
  const leftScore = Number(left && left.score) || 0;
  const rightScore = Number(right && right.score) || 0;
  if (rightScore !== leftScore) {
    return rightScore - leftScore;
  }

  const leftRelease = releaseDateTimestamp(left && left.release_date);
  const rightRelease = releaseDateTimestamp(right && right.release_date);
  if (rightRelease !== leftRelease) {
    return rightRelease - leftRelease;
  }

  const leftTitle = String((left && left.title) || "");
  const rightTitle = String((right && right.title) || "");
  if (leftTitle !== rightTitle) {
    return leftTitle.localeCompare(rightTitle);
  }

  return String((left && left.slug) || "").localeCompare(String((right && right.slug) || ""));
}

let searchResultsLayoutFrame = 0;

function layoutSearchResultsMasonry() {
  if (!elements.searchResults) {
    return;
  }

  const gridStyles = window.getComputedStyle(elements.searchResults);
  const autoRows = Number.parseFloat(gridStyles.getPropertyValue("grid-auto-rows"));
  const rowGap = Number.parseFloat(gridStyles.getPropertyValue("row-gap"));
  if (!Number.isFinite(autoRows) || autoRows <= 0 || !Number.isFinite(rowGap)) {
    return;
  }

  elements.searchResults.querySelectorAll(".search-result-card").forEach((card) => {
    card.style.gridRowEnd = "span 1";
  });

  elements.searchResults.querySelectorAll(".search-result-card").forEach((card) => {
    const cardHeight = card.getBoundingClientRect().height;
    const span = Math.max(1, Math.ceil((cardHeight + rowGap) / (autoRows + rowGap)));
    card.style.gridRowEnd = `span ${span}`;
  });
}

function scheduleSearchResultsLayout() {
  if (searchResultsLayoutFrame) {
    window.cancelAnimationFrame(searchResultsLayoutFrame);
  }
  searchResultsLayoutFrame = window.requestAnimationFrame(() => {
    searchResultsLayoutFrame = 0;
    layoutSearchResultsMasonry();
  });
}

function renderSearchResults() {
  const matches = Array.isArray(state.search.matches)
    ? [...state.search.matches].sort(compareSearchMatches)
    : [];
  if (!matches.length) {
    elements.searchPanel.classList.add("hidden");
    elements.searchMeta.textContent = "";
    elements.searchResults.innerHTML = "";
    scheduleSearchResultsLayout();
    return;
  }

  const totalMatches = Number(state.search.total_matches || matches.length || 0);
  elements.searchPanel.classList.remove("hidden");
  elements.searchMeta.textContent = t("searchMeta", { shown: matches.length, total: totalMatches });
  elements.searchResults.innerHTML = matches.map((match) => {
    const title = match.title || t("searchLoadingTitle");
    const releaseDate = match.release_date || "-";
    const cover = match.cover_url
      ? `<img class="search-result-cover-image" src="${escapeHtml(match.cover_url)}" alt="${escapeHtml(title)}">`
      : `<div class="search-result-cover-placeholder">${escapeHtml(t("noCover"))}</div>`;
    return `
      <button class="search-result-card" type="button" data-slug="${escapeHtml(match.slug || "")}">
        <div class="search-result-cover">
          ${cover}
        </div>
        <div class="search-result-body">
          <h3 class="search-result-title">${escapeHtml(title)}</h3>
          <div class="search-result-facts">
            <div class="search-result-fact">
              <span class="search-result-fact-label">${escapeHtml(t("labelRelease"))}</span>
              <span class="search-result-fact-value">${escapeHtml(releaseDate)}</span>
            </div>
          </div>
        </div>
      </button>
    `;
  }).join("");

  elements.searchResults.querySelectorAll(".search-result-cover-image").forEach((image) => {
    if (image.complete) {
      return;
    }
    image.addEventListener("load", scheduleSearchResultsLayout, { once: true });
    image.addEventListener("error", scheduleSearchResultsLayout, { once: true });
  });
  scheduleSearchResultsLayout();
}

function mergeSearchMatchDetails(slug, game) {
  const normalizedSlug = normalizeSlug(slug);
  if (!normalizedSlug || !Array.isArray(state.search.matches) || state.search.matches.length === 0) {
    return false;
  }

  let updated = false;
  state.search.matches = state.search.matches.map((match) => {
    if (normalizeSlug(match.slug) !== normalizedSlug) {
      return match;
    }
    updated = true;
    return {
      ...match,
      title: game.title || match.title || null,
      platform: game.platform || match.platform || null,
      release_date: game.release_date || match.release_date || null,
      cover_url: game.cover_url || match.cover_url || null,
    };
  });
  return updated;
}

function removeSearchMatch(slug) {
  const normalizedSlug = normalizeSlug(slug);
  if (!normalizedSlug || !Array.isArray(state.search.matches) || state.search.matches.length === 0) {
    return false;
  }

  const nextMatches = state.search.matches.filter((match) => normalizeSlug(match.slug) !== normalizedSlug);
  if (nextMatches.length === state.search.matches.length) {
    return false;
  }

  state.search.matches = nextMatches;
  state.search.total_matches = Math.max(0, nextMatches.length);
  if (state.search.selected && normalizeSlug(state.search.selected.slug) === normalizedSlug) {
    state.search.selected = null;
  }
  return true;
}

async function hydrateSearchResults(requestId) {
  const matches = Array.isArray(state.search.matches) ? [...state.search.matches] : [];
  for (const match of matches) {
    const slug = normalizeSlug(match.slug);
    if (!slug) {
      continue;
    }
    try {
      const game = await fetchJson(`/api/game?slug=${encodeURIComponent(slug)}`);
      if (requestId !== state.requestId) {
        return;
      }
      if (mergeSearchMatchDetails(slug, game)) {
        renderSearchResults();
      }
    } catch {
      if (requestId !== state.requestId) {
        return;
      }
      if (removeSearchMatch(slug)) {
        renderSearchResults();
        if (!state.search.matches.length) {
          showError("errorNoMatch", { query: state.search.query || elements.input.value || "" });
        }
      }
    }
  }
}

function clearStatus() {
  state.status = null;
  renderStatus();
}

function showError(key, params = {}) {
  state.status = { key, params };
  renderStatus();
}

function renderStatus() {
  if (!elements.statusCard || !state.status) {
    if (!elements.statusCard) {
      return;
    }
    elements.statusCard.classList.add("hidden");
    elements.statusCard.innerHTML = "";
    return;
  }
  elements.statusCard.classList.remove("hidden");
  elements.statusCard.dataset.tone = "error";
  elements.statusCard.innerHTML = t(state.status.key, state.status.params);
}

function showSearchRoute() {
  if (window.location.pathname === "/") {
    window.history.replaceState({}, "", "/");
    return;
  }
  window.history.pushState({}, "", "/");
}

function renderGame() {
  if (!state.game) {
    elements.results.classList.add("hidden");
    elements.emptyState.classList.remove("hidden");
    return;
  }

  elements.results.classList.remove("hidden");
  elements.emptyState.classList.add("hidden");

  const game = state.game;
  elements.gameTitle.textContent = game.title || game.slug || t("unnamedGame");
  elements.gamePlatform.textContent = game.platform || "-";
  elements.gameRelease.textContent = game.release_date || "-";
  elements.gameRating.textContent = game.rating || "-";
  elements.gameScrapedAt.textContent = formatDate(game.scraped_at);
  elements.dataSourceBadge.textContent = game.auto_crawled ? t("dataSourceAutoCrawled") : t("dataSourceCached");
  elements.criticScore.textContent = scoreText(game.critic_score);
  elements.criticCount.textContent = countText(game.critic_review_count);
  elements.userScore.textContent = scoreText(game.user_score);
  elements.userCount.textContent = countText(game.user_review_count);
  elements.techSlug.textContent = game.slug || "-";
  elements.techSource.textContent = game.auto_crawled ? t("techSourceAutoCrawled") : t("techSourceCached");

  if (game.cover_url) {
    elements.coverImage.src = game.cover_url;
    elements.coverImage.alt = `${game.title || game.slug || t("unnamedGame")} cover`;
    elements.coverImage.classList.remove("hidden");
    elements.coverPlaceholder.classList.add("hidden");
  } else {
    elements.coverImage.classList.add("hidden");
    elements.coverPlaceholder.classList.remove("hidden");
  }
}

function reviewMeta(review, type) {
  if (type === "critic") {
    return {
      source: review.publicationName || review.author || t("unknownCritic"),
      score: review.score ?? "-",
      date: review.date || "-",
    };
  }
  return {
    source: review.author || t("unknownPlayer"),
    score: review.score ?? "-",
    date: review.date || "-",
  };
}

function renderReviewCards(reviews, type, limit) {
  if (!reviews.length) {
    return `<div class="review-empty">${type === "critic" ? t("noCriticReviews") : t("noUserReviews")}</div>`;
  }

  return reviews.slice(0, limit).map((review) => {
    const meta = reviewMeta(review, type);
    const quote = review.quote || t("missingQuote");
    return `
      <article class="review-card">
        <div class="review-head">
          <h3 class="review-source">${escapeHtml(meta.source)}</h3>
          <span class="review-score">${escapeHtml(meta.score)}</span>
        </div>
        <p class="review-date">${escapeHtml(meta.date)}</p>
        <p class="review-quote">${escapeHtml(quote)}</p>
      </article>
    `;
  }).join("");
}

function renderReviews() {
  const criticReviews = state.reviews.critic_reviews || [];
  const userReviews = state.reviews.user_reviews || [];
  const counts = state.reviews.counts || {};
  const criticCount = Number(counts.critic_reviews || criticReviews.length || 0);
  const userCount = Number(counts.user_reviews || userReviews.length || 0);

  elements.reviewSummary.textContent = state.reviewsLoading
    ? t("reviewSummaryLoading")
    : t("reviewSummaryCounts", { criticCount, userCount });

  elements.criticPanel.innerHTML = renderReviewCards(criticReviews, "critic", state.visibleCritic);
  elements.userPanel.innerHTML = renderReviewCards(userReviews, "user", state.visibleUser);
  elements.techCriticTotal.textContent = String(criticCount);
  elements.techUserTotal.textContent = String(userCount);

  elements.criticMore.classList.toggle("hidden", criticReviews.length <= state.visibleCritic);
  elements.userMore.classList.toggle("hidden", userReviews.length <= state.visibleUser);
  elements.criticMore.disabled = state.reviewsLoading;
  elements.userMore.disabled = state.reviewsLoading;

  const showingCritic = state.activeTab === "critic";
  elements.tabCritic.classList.toggle("active", showingCritic);
  elements.tabUser.classList.toggle("active", !showingCritic);
  elements.tabCritic.setAttribute("aria-selected", showingCritic ? "true" : "false");
  elements.tabUser.setAttribute("aria-selected", showingCritic ? "false" : "true");
  elements.criticPanel.classList.toggle("hidden", !showingCritic);
  elements.criticMore.classList.toggle("hidden", !showingCritic || criticReviews.length <= state.visibleCritic);
  elements.userPanel.classList.toggle("hidden", showingCritic);
  elements.userMore.classList.toggle("hidden", showingCritic || userReviews.length <= state.visibleUser);
}

function setLoading(isLoading) {
  state.isBusy = Boolean(isLoading);
  elements.submitButton.disabled = state.isBusy;
  elements.submitButton.textContent = state.isBusy ? t("submitLoading") : t("submitIdle");
}

function openGameSlug(slug, replace = false) {
  const normalized = normalizeSlug(slug);
  if (!normalized) {
    return;
  }
  elements.input.value = "";
  const nextPath = `/game/${encodeURIComponent(normalized)}`;
  if (replace) {
    window.location.replace(nextPath);
    return;
  }
  window.location.assign(nextPath);
}

function applyLocale() {
  document.documentElement.lang = t("htmlLang");
  document.title = t("pageTitle");
  elements.langSwitch.setAttribute("aria-label", t("languageGroupLabel"));
  elements.langZh.classList.toggle("active", state.locale === "zh");
  elements.langEn.classList.toggle("active", state.locale === "en");
  elements.langZh.setAttribute("aria-pressed", state.locale === "zh" ? "true" : "false");
  elements.langEn.setAttribute("aria-pressed", state.locale === "en" ? "true" : "false");
  elements.pageTitle.textContent = t("pageTitle");
  elements.intro.textContent = t("introHint");
  elements.input.placeholder = t("inputPlaceholder");
  elements.recentTitle.textContent = t("recentTitle");
  elements.clearRecent.textContent = t("clearRecent");
  elements.searchTitle.textContent = t("searchTitle");
  elements.emptyTitle.textContent = t("emptyTitle");
  elements.emptyCopy.textContent = t("emptyCopy");
  elements.coverPlaceholder.textContent = t("noCover");
  elements.profileKicker.textContent = t("profileKicker");
  elements.labelPlatform.textContent = t("labelPlatform");
  elements.labelRelease.textContent = t("labelRelease");
  elements.labelRating.textContent = t("labelRating");
  elements.labelScrapedAt.textContent = t("labelScrapedAt");
  elements.criticScoreLabel.textContent = t("criticScoreLabel");
  elements.userScoreLabel.textContent = t("userScoreLabel");
  elements.reviewsTitle.textContent = t("reviewsTitle");
  elements.reviewTabBar.setAttribute("aria-label", t("reviewTabsLabel"));
  elements.tabCritic.textContent = t("tabCritic");
  elements.tabUser.textContent = t("tabUser");
  elements.criticMore.textContent = t("criticMore");
  elements.userMore.textContent = t("userMore");
  elements.technicalSummary.textContent = t("technicalSummary");
  elements.labelTechSlug.textContent = t("techSlug");
  elements.labelTechSource.textContent = t("techSource");
  elements.labelTechCriticTotal.textContent = t("techCriticTotal");
  elements.labelTechUserTotal.textContent = t("techUserTotal");

  setLoading(state.isBusy);
  renderRecentGames();
  renderSearchResults();
  renderGame();
  renderReviews();
  renderStatus();
}

function setLocale(locale) {
  if (locale !== "zh" && locale !== "en") {
    return;
  }
  state.locale = locale;
  saveLocale(locale);
  applyLocale();
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  const payload = await response.json().catch(() => ({ ok: false, error: t("errorResponseParse") }));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || t("errorRequestFailed", { status: response.status }));
  }
  return payload.data;
}

async function searchGames(query) {
  const normalized = normalizeSlug(query);
  if (!normalized) {
    showError("errorInvalidSearch");
    return;
  }

  elements.input.value = normalized;
  state.requestId += 1;
  const requestId = state.requestId;
  resetSearchState();
  state.slug = "";
  state.game = null;
  state.reviews = { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } };
  state.visibleCritic = INITIAL_VISIBLE_REVIEWS;
  state.visibleUser = INITIAL_VISIBLE_REVIEWS;
  state.gameLoading = false;
  state.reviewsLoading = false;
  state.gameError = "";
  state.reviewsError = "";

  clearStatus();
  setLoading(true);
  renderSearchResults();
  renderGame();
  renderReviews();

  try {
    const searchResult = await fetchJson(`/api/search?q=${encodeURIComponent(normalized)}`);
    if (requestId !== state.requestId) {
      return;
    }
    state.search = searchResult;
    renderSearchResults();

    if (searchResult.selected && searchResult.selected.slug) {
      openGameSlug(searchResult.selected.slug);
      return;
    }

    showSearchRoute();

    if (!(searchResult.matches || []).length) {
      showError("errorNoMatch", { query: normalized });
      return;
    }

    clearStatus();
    void hydrateSearchResults(requestId);
  } catch (error) {
    if (requestId !== state.requestId) {
      return;
    }
    showSearchRoute();
    showError("errorSearchFailed", { error: String(error.message || error) });
  } finally {
    if (requestId === state.requestId) {
      setLoading(false);
    }
  }
}

async function loadSlug(slug) {
  const normalized = normalizeSlug(slug);
  if (!normalized) {
    showError("errorInvalidRoute");
    return;
  }

  state.requestId += 1;
  const requestId = state.requestId;
  state.slug = normalized;
  state.game = null;
  resetSearchState();
  state.reviews = { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } };
  state.visibleCritic = INITIAL_VISIBLE_REVIEWS;
  state.visibleUser = INITIAL_VISIBLE_REVIEWS;
  state.gameLoading = true;
  state.reviewsLoading = false;
  state.gameError = "";
  state.reviewsError = "";

  clearStatus();
  setLoading(true);
  renderSearchResults();
  renderGame();
  renderReviews();

  try {
    const game = await fetchJson(`/api/game?slug=${encodeURIComponent(normalized)}`);
    if (requestId !== state.requestId) {
      return;
    }
    state.game = game;
    state.gameLoading = false;
    renderGame();
    saveRecentGame({ slug: normalized, title: game.title || normalized });

    state.reviewsLoading = true;
    renderReviews();
    const reviews = await fetchJson(`/api/reviews?slug=${encodeURIComponent(normalized)}`);
    if (requestId !== state.requestId) {
      return;
    }
    state.reviews = reviews;
    state.reviewsLoading = false;
    renderReviews();
    clearStatus();
  } catch (error) {
    if (requestId !== state.requestId) {
      return;
    }
    state.gameLoading = false;
    state.reviewsLoading = false;
    state.gameError = String(error.message || error);
    renderReviews();
    renderGame();
    showError("errorLookupFailed", { error: state.gameError });
  } finally {
    if (requestId === state.requestId) {
      setLoading(false);
    }
  }
}

function applyRoute(slug, replace = false) {
  const normalized = normalizeSlug(slug);
  const nextPath = normalized ? `/game/${encodeURIComponent(normalized)}` : "/";
  if (replace) {
    window.history.replaceState({}, "", nextPath);
  } else {
    window.history.pushState({}, "", nextPath);
  }
  elements.input.value = "";
  if (normalized) {
    loadSlug(normalized);
  } else {
    state.slug = "";
    state.game = null;
    resetSearchState();
    state.reviews = { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } };
    renderSearchResults();
    renderGame();
    renderReviews();
    clearStatus();
  }
}

function routeSlugFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts.length === 2 && parts[0] === "game") {
    return decodeURIComponent(parts[1]);
  }
  return "";
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  searchGames(elements.input.value);
});

elements.langZh.addEventListener("click", () => {
  setLocale("zh");
});

elements.langEn.addEventListener("click", () => {
  setLocale("en");
});

window.addEventListener("resize", scheduleSearchResultsLayout);

elements.recentList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const slug = target.dataset.slug;
  if (slug) {
    openGameSlug(slug);
  }
});

elements.searchResults.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const button = target.closest("[data-slug]");
  if (!(button instanceof HTMLElement)) {
    return;
  }
  const slug = button.dataset.slug;
  if (slug) {
    openGameSlug(slug);
  }
});

elements.clearRecent.addEventListener("click", () => {
  clearRecentGames();
});

elements.tabCritic.addEventListener("click", () => {
  state.activeTab = "critic";
  renderReviews();
});

elements.tabUser.addEventListener("click", () => {
  state.activeTab = "user";
  renderReviews();
});

elements.criticMore.addEventListener("click", () => {
  state.visibleCritic += REVIEW_INCREMENT;
  renderReviews();
});

elements.userMore.addEventListener("click", () => {
  state.visibleUser += REVIEW_INCREMENT;
  renderReviews();
});

window.addEventListener("popstate", () => {
  const slug = routeSlugFromPath();
  elements.input.value = "";
  if (slug) {
    loadSlug(slug);
  } else {
    state.game = null;
    resetSearchState();
    renderSearchResults();
    renderGame();
    renderReviews();
    clearStatus();
  }
});

applyLocale();
resetSearchState();
renderSearchResults();
renderReviews();
const initialSlug = routeSlugFromPath();
if (initialSlug) {
  applyRoute(initialSlug, true);
} else {
  clearStatus();
}
