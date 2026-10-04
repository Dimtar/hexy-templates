// Theme toggle, shared by every page. The choice is a per-browser convenience,
// so storage failures (private mode, blocked storage) just mean it isn't kept.
(function () {
  const root = document.documentElement;
  const button = document.querySelector(".theme-toggle");
  if (!button) return;
  button.addEventListener("click", function () {
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });
})();
