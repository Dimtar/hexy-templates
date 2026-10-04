// Library search: filters the server-rendered cards in place, so the page
// still lists every app with JavaScript off.
(function () {
  const input = document.getElementById("q");
  const status = document.getElementById("status");
  const chips = Array.from(document.querySelectorAll(".chip"));
  const cards = Array.from(document.querySelectorAll(".card"));
  const count = document.getElementById("count");
  const empty = document.getElementById("empty");
  let category = "";

  const params = new URLSearchParams(location.search);
  input.value = params.get("q") || "";
  category = params.get("category") || "";
  status.value = params.get("status") || "";

  function apply() {
    const terms = input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const card of cards) {
      const text = card.dataset.search;
      const ok =
        terms.every((t) => text.includes(t)) &&
        (!category || card.dataset.cats.split(" ").includes(category)) &&
        (!status.value || card.dataset.status === status.value);
      card.hidden = !ok;
      if (ok) shown++;
    }
    count.textContent = shown === cards.length ? `${shown} apps` : `${shown} of ${cards.length} apps`;
    empty.hidden = shown > 0;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.cat === category)));

    const next = new URLSearchParams();
    if (input.value.trim()) next.set("q", input.value.trim());
    if (category) next.set("category", category);
    if (status.value) next.set("status", status.value);
    const qs = next.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  input.addEventListener("input", apply);
  status.addEventListener("change", apply);
  chips.forEach((chip) =>
    chip.addEventListener("click", () => {
      category = chip.dataset.cat === category ? "" : chip.dataset.cat;
      apply();
    })
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== input) {
      e.preventDefault();
      input.focus();
    }
  });
  apply();
})();
