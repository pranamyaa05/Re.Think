export const COOKIE_NAME = "rethink_session";
export const ONE_YEAR_MS = 1000 * 60 * 60 * 24 * 365;

/**
 * Send the browser to the app's sign-in page. The page offers the configured
 * OAuth provider when one is set up, and otherwise the development sign-in
 * that the server enables explicitly.
 */
export const startLogin = () => {
  window.location.href = "/login";
};
