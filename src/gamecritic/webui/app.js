const RECENT_SLUGS_KEY = "gamecritic_recent_slugs";
const INITIAL_VISIBLE_REVIEWS = 20;
const REVIEW_INCREMENT = 20;

const state = {
  slug: "",
  game: null,
  reviews: { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } },
  activeTab: "critic",
  visibleCritic: INITIAL_VISIBLE_REVIEWS,
  visibleUser: INITIAL_VISIBLE_REVIEWS,
  gameLoading: false,
  reviewsLoading: false,
  gameError: "",
  reviewsError: "",
  requestId: 0,
};

const elements = {
  form: document.getElementById("slug-form"),
  input: document.getElementById("slug-input"),
  submitButton: document.getElementById("submit-button"),
  recentList: document.getElementById("recent-list"),
  clearRecent: document.getElementById("clear-recent"),
  emptyState: document.getElementById("empty-state"),
  results: document.getElementById("results"),
  statusCard: document.getElementById("status-card"),
  coverImage: document.getElementById("cover-image"),
  coverPlaceholder: document.getElementById("cover-placeholder"),
  gameTitle: document.getElementById("game-title"),
  gamePlatform: document.getElementById("game-platform"),
  gameRelease: document.getElementById("game-release"),
  gameRating: document.getElementById("game-rating"),
  gameScrapedAt: document.getElementById("game-scraped-at"),
  dataSourceBadge: document.getElementById("data-source-badge"),
  criticScore: document.getElementById("critic-score"),
  criticCount: document.getElementById("critic-count"),
  userScore: document.getElementById("user-score"),
  userCount: document.getElementById("user-count"),
  reviewSummary: document.getElementById("review-summary"),
  tabCritic: document.getElementById("tab-critic"),
  tabUser: document.getElementById("tab-user"),
  criticPanel: document.getElementById("critic-panel"),
  userPanel: document.getElementById("user-panel"),
  criticMore: document.getElementById("critic-more"),
  userMore: document.getElementById("user-more"),
  techSlug: document.getElementById("tech-slug"),
  techSource: document.getElementById("tech-source"),
  techCriticTotal: document.getElementById("tech-critic-total"),
  techUserTotal: document.getElementById("tech-user-total"),
};

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
  return parsed.toLocaleString("zh-CN", {
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
  return `${numeric} 条评论`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function getRecentSlugs() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_SLUGS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string" && item.trim()) : [];
  } catch {
    return [];
  }
}

function saveRecentSlug(slug) {
  const normalized = normalizeSlug(slug);
  if (!normalized) {
    return;
  }
  const next = [normalized, ...getRecentSlugs().filter((item) => item !== normalized)].slice(0, 8);
  localStorage.setItem(RECENT_SLUGS_KEY, JSON.stringify(next));
  renderRecentSlugs();
}

function clearRecentSlugs() {
  localStorage.removeItem(RECENT_SLUGS_KEY);
  renderRecentSlugs();
}

function renderRecentSlugs() {
  const recent = getRecentSlugs();
  if (recent.length === 0) {
    elements.recentList.classList.add("empty");
    elements.recentList.textContent = "还没有最近访问记录。";
    return;
  }

  elements.recentList.classList.remove("empty");
  elements.recentList.innerHTML = recent
    .map((slug) => `<button class="recent-chip" type="button" data-slug="${escapeHtml(slug)}">${escapeHtml(slug)}</button>`)
    .join("");
}

function setStatus(message, tone = "neutral") {
  if (!message) {
    elements.statusCard.classList.add("hidden");
    elements.statusCard.innerHTML = "";
    return;
  }
  elements.statusCard.classList.remove("hidden");
  elements.statusCard.dataset.tone = tone;
  elements.statusCard.innerHTML = message;
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
  elements.gameTitle.textContent = game.title || game.slug || "未命名游戏";
  elements.gamePlatform.textContent = game.platform || "-";
  elements.gameRelease.textContent = game.release_date || "-";
  elements.gameRating.textContent = game.rating || "-";
  elements.gameScrapedAt.textContent = formatDate(game.scraped_at);
  elements.dataSourceBadge.textContent = game.auto_crawled ? "本次请求触发抓取" : "命中本地缓存";
  elements.criticScore.textContent = scoreText(game.critic_score);
  elements.criticCount.textContent = countText(game.critic_review_count);
  elements.userScore.textContent = scoreText(game.user_score);
  elements.userCount.textContent = countText(game.user_review_count);
  elements.techSlug.textContent = game.slug || "-";
  elements.techSource.textContent = game.auto_crawled ? "接口触发抓取后落库" : "直接读取现有数据库";

  if (game.cover_url) {
    elements.coverImage.src = game.cover_url;
    elements.coverImage.alt = `${game.title || game.slug || "game"} cover`;
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
      source: review.publicationName || review.author || "Unknown critic",
      score: review.score ?? "-",
      date: review.date || "-",
    };
  }
  return {
    source: review.author || "Unknown player",
    score: review.score ?? "-",
    date: review.date || "-",
  };
}

function renderReviewCards(reviews, type, limit) {
  if (!reviews.length) {
    return `<div class="review-empty">当前没有${type === "critic" ? "媒体" : "用户"}评论数据。</div>`;
  }

  return reviews.slice(0, limit).map((review) => {
    const meta = reviewMeta(review, type);
    const quote = review.quote || "该评论没有摘要文本。";
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

  elements.reviewSummary.textContent = state.reviewsLoading
    ? "正在加载评论数据..."
    : `媒体 ${counts.critic_reviews || criticReviews.length} 条 · 用户 ${counts.user_reviews || userReviews.length} 条`;

  elements.criticPanel.innerHTML = renderReviewCards(criticReviews, "critic", state.visibleCritic);
  elements.userPanel.innerHTML = renderReviewCards(userReviews, "user", state.visibleUser);
  elements.techCriticTotal.textContent = String(counts.critic_reviews || criticReviews.length || 0);
  elements.techUserTotal.textContent = String(counts.user_reviews || userReviews.length || 0);

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
  elements.submitButton.disabled = isLoading;
  elements.submitButton.textContent = isLoading ? "检索中..." : "检索";
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  const payload = await response.json().catch(() => ({ ok: false, error: "响应解析失败" }));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败: ${response.status}`);
  }
  return payload.data;
}

async function loadSlug(slug) {
  const normalized = normalizeSlug(slug);
  if (!normalized) {
    setStatus("请输入一个有效的 slug。", "error");
    return;
  }

  state.requestId += 1;
  const requestId = state.requestId;
  state.slug = normalized;
  state.game = null;
  state.reviews = { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } };
  state.visibleCritic = INITIAL_VISIBLE_REVIEWS;
  state.visibleUser = INITIAL_VISIBLE_REVIEWS;
  state.gameLoading = true;
  state.reviewsLoading = false;
  state.gameError = "";
  state.reviewsError = "";

  setLoading(true);
  renderGame();
  renderReviews();
  setStatus("<strong>正在获取游戏基础信息。</strong><br>首次检索某个 slug 时，接口可能需要几秒到十几秒来抓取并落库。");

  try {
    const game = await fetchJson(`/api/game?slug=${encodeURIComponent(normalized)}`);
    if (requestId !== state.requestId) {
      return;
    }
    state.game = game;
    state.gameLoading = false;
    renderGame();
    saveRecentSlug(normalized);
    setStatus(
      game.auto_crawled
        ? "<strong>已完成游戏信息抓取。</strong><br>接下来加载媒体评论和用户评论。"
        : "<strong>已命中本地缓存。</strong><br>接下来加载媒体评论和用户评论。"
    );

    state.reviewsLoading = true;
    renderReviews();
    const reviews = await fetchJson(`/api/reviews?slug=${encodeURIComponent(normalized)}`);
    if (requestId !== state.requestId) {
      return;
    }
    state.reviews = reviews;
    state.reviewsLoading = false;
    renderReviews();
    setStatus(
      `<strong>已完成检索。</strong><br>当前显示 <strong>${escapeHtml(normalized)}</strong> 的游戏资料和评论。`,
      "success"
    );
  } catch (error) {
    if (requestId !== state.requestId) {
      return;
    }
    state.gameLoading = false;
    state.reviewsLoading = false;
    state.gameError = String(error.message || error);
    renderReviews();
    renderGame();
    setStatus(`<strong>检索失败。</strong><br>${escapeHtml(state.gameError)}`, "error");
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
  elements.input.value = normalized;
  if (normalized) {
    loadSlug(normalized);
  } else {
    state.slug = "";
    state.game = null;
    state.reviews = { critic_reviews: [], user_reviews: [], counts: { critic_reviews: 0, user_reviews: 0 } };
    renderGame();
    renderReviews();
    setStatus("");
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
  applyRoute(elements.input.value);
});

elements.recentList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const slug = target.dataset.slug;
  if (slug) {
    applyRoute(slug);
  }
});

elements.clearRecent.addEventListener("click", () => {
  clearRecentSlugs();
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
  elements.input.value = slug;
  if (slug) {
    loadSlug(slug);
  } else {
    state.game = null;
    renderGame();
    renderReviews();
    setStatus("");
  }
});

renderRecentSlugs();
renderReviews();
const initialSlug = routeSlugFromPath();
if (initialSlug) {
  elements.input.value = initialSlug;
  applyRoute(initialSlug, true);
} else {
  setStatus("");
}
