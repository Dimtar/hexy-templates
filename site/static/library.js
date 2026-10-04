// Library search: filters the server-rendered cards in place, so the page
// still lists every app with JavaScript off.
(function () {
  const input = document.getElementById("q");
  const segs = Array.from(document.querySelectorAll(".seg"));
  const curatedBtn = document.getElementById("curated");
  const chips = Array.from(document.querySelectorAll(".chip"));
  const cards = Array.from(document.querySelectorAll(".card"));
  const count = document.getElementById("count");
  const empty = document.getElementById("empty");
  let category = "";
  let status = "";
  let curatedOnly = false;

  const params = new URLSearchParams(location.search);
  input.value = params.get("q") || "";
  category = params.get("category") || "";
  status = params.get("status") || "";
  curatedOnly = params.get("curated") === "1";

  function apply() {
    const terms = input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const card of cards) {
      const text = card.dataset.search;
      const ok =
        terms.every((t) => text.includes(t)) &&
        (!category || card.dataset.cats.split(" ").includes(category)) &&
        (!status || card.dataset.status === status) &&
        (!curatedOnly || card.dataset.curated === "yes");
      card.hidden = !ok;
      if (ok) shown++;
    }
    count.textContent = shown === cards.length ? `${shown} apps` : `${shown} of ${cards.length} apps`;
    empty.hidden = shown > 0;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.cat === category)));
    curatedBtn.addEventListener("click", () => {
    curatedOnly = !curatedOnly;
    apply();
  });
  segs.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === status)));
    curatedBtn.setAttribute("aria-pressed", String(curatedOnly));

    const next = new URLSearchParams();
    if (input.value.trim()) next.set("q", input.value.trim());
    if (category) next.set("category", category);
    if (status) next.set("status", status);
    if (curatedOnly) next.set("curated", "1");
    const qs = next.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  input.addEventListener("input", apply);
  segs.forEach((b) =>
    b.addEventListener("click", () => {
      status = b.dataset.status;
      apply();
    })
  );
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
