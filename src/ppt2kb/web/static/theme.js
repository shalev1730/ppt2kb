/* Applies the theme before the page is painted (loaded synchronously in <head>; CSP allows only same-origin scripts).
   A choice made with the sun/moon toggle is stored per browser in localStorage ("ppt2kb.theme").
   Without a stored choice the system preference is followed (the 1.0/1.1 UI already did), light otherwise. */
(function () {
  var theme = null;
  try { theme = localStorage.getItem("ppt2kb.theme"); } catch (e) { /* storage unavailable */ }
  if (theme !== "dark" && theme !== "light") {
    theme = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
