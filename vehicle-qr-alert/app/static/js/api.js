/* ============================================================
   Shared front-end helpers.

   Plain-language summary:
   This is a plain HTML/JS front end (no React/build step) that
   talks to the FastAPI backend over fetch(). After login, the
   server hands back a JWT (a signed token proving who you are).
   We store it in localStorage and attach it as an Authorization
   header on every request that needs it. This is standard for a
   local demo/portfolio project; a production app would likely use
   an httpOnly cookie instead so client-side JS can't read the
   token -- worth mentioning as a trade-off in an interview.
   ============================================================ */

const TOKEN_KEY = "vqa_token";

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function isLoggedIn() {
  return !!getToken();
}

function requireAuthOrRedirect() {
  if (!isLoggedIn()) {
    window.location.href = "/login";
  }
}

function logout() {
  clearToken();
  window.location.href = "/";
}

/**
 * Wrapper around fetch() that adds JSON headers and the auth token
 * automatically, and throws a readable error on non-2xx responses.
 */
async function api(path, { method = "GET", body = null, auth = false, form = false } = {}) {
  const headers = {};
  let payload = body;

  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(body).toString();
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, { method, headers, body: payload });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;

  if (!res.ok) {
    const message = (data && data.detail) || `Request failed (${res.status})`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

function showBanner(el, message, type = "error") {
  el.textContent = message;
  el.className = `alert-banner show ${type}`;
}

function hideBanner(el) {
  el.className = "alert-banner";
}

/** Small helper to reflect login state in the top nav on every page. */
function paintNav() {
  const authLinks = document.querySelectorAll("[data-auth-only]");
  const guestLinks = document.querySelectorAll("[data-guest-only]");
  authLinks.forEach((el) => (el.style.display = isLoggedIn() ? "" : "none"));
  guestLinks.forEach((el) => (el.style.display = isLoggedIn() ? "none" : ""));
}

document.addEventListener("DOMContentLoaded", paintNav);
