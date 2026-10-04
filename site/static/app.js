// App page: links the explanation boxes to the script lines they describe.
// Hovering or focusing a box highlights its lines, scrolls them into view
// inside the code pane and draws a connector from the box to the code.
(function () {
  const code = document.getElementById("code");
  const boxes = Array.from(document.querySelectorAll(".box"));
  const lines = Array.from(code.querySelectorAll(".ln"));
  const connector = document.getElementById("connector");
  const path = connector.querySelector("path");
  let active = null;
  let pinned = null;

  function linesOf(box) {
    const start = +box.dataset.start, end = +box.dataset.end;
    return lines.slice(start - 1, end);
  }

  function draw() {
    if (!active || getComputedStyle(connector).display === "none") {
      connector.classList.remove("show");
      return;
    }
    const target = linesOf(active);
    const first = target[0].getBoundingClientRect();
    const last = target[target.length - 1].getBoundingClientRect();
    const pane = code.getBoundingClientRect();
    const box = active.getBoundingClientRect();
    // Aim at the middle of the visible part of the highlighted range.
    const top = Math.max(first.top, pane.top), bottom = Math.min(last.bottom, pane.bottom);
    if (bottom <= top) {
      connector.classList.remove("show");
      return;
    }
    const x1 = pane.right - 6, y1 = (top + bottom) / 2;
    const x2 = box.left - 12, y2 = box.top + 25;
    const mid = (x1 + x2) / 2;
    path.setAttribute("d", `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`);
    connector.classList.add("show");
  }

  function activate(box, scroll) {
    if (active === box) return draw();
    if (active) {
      active.classList.remove("active");
      linesOf(active).forEach((l) => l.classList.remove("hl"));
      document.querySelectorAll(".marker.active").forEach((m) => m.classList.remove("active"));
    }
    active = box;
    if (!box) return draw();
    box.classList.add("active");
    const target = linesOf(box);
    target.forEach((l) => l.classList.add("hl"));
    document.querySelectorAll(`.marker[data-box="${box.dataset.box}"]`).forEach((m) => m.classList.add("active"));
    if (scroll) {
      // Scroll only the code pane, never the page, so the box stays under the cursor.
      const first = target[0], last = target[target.length - 1];
      const above = first.offsetTop < code.scrollTop + 8;
      const below = last.offsetTop + last.offsetHeight > code.scrollTop + code.clientHeight - 8;
      if (above || below) {
        const span = last.offsetTop + last.offsetHeight - first.offsetTop;
        code.scrollTo({ top: first.offsetTop - Math.max(16, (code.clientHeight - span) / 2), behavior: "smooth" });
      }
    }
    draw();
  }

  boxes.forEach((box) => {
    box.addEventListener("mouseenter", () => activate(box, true));
    box.addEventListener("mouseleave", () => activate(pinned, false));
    box.addEventListener("focus", () => activate(box, true));
    box.addEventListener("click", () => {
      pinned = pinned === box ? null : box;
      activate(pinned || box, true);
      // On narrow screens the code sits above the boxes; bring it into view.
      if (pinned && matchMedia("(max-width: 960px)").matches) {
        code.closest(".code-card").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const sideBySide = matchMedia("(min-width: 961px)");

  // Bring a box on screen if it isn't already. Uses the smallest scroll that
  // works, so a box that's already visible never makes the page jump.
  function reveal(box) {
    const r = box.getBoundingClientRect();
    const headerBottom = 76;
    if (r.top >= headerBottom && r.bottom <= innerHeight - 16) return;
    box.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "nearest" });
  }

  function boxForLine(ln) {
    const n = +ln.dataset.line;
    const covering = boxes.filter((b) => n >= +b.dataset.start && n <= +b.dataset.end);
    // Prefer the most specific (shortest) range.
    covering.sort((a, b) => (a.dataset.end - a.dataset.start) - (b.dataset.end - b.dataset.start));
    return covering[0];
  }

  // Hovering a code line lights up the box that covers it. If the mouse rests
  // there for a moment, the page scrolls that box into view; waiting first
  // stops the page from lurching about while the mouse just passes over code.
  // The code column is sticky, so it stays put under the mouse while the
  // explanations scroll past beside it.
  let revealTimer = 0;
  code.addEventListener("mouseover", (e) => {
    const ln = e.target.closest(".ln");
    if (!ln) return;
    const box = boxForLine(ln);
    if (!box || box === active) return;
    activate(box, false);
    clearTimeout(revealTimer);
    if (sideBySide.matches) revealTimer = setTimeout(() => reveal(box), 350);
  });
  code.addEventListener("mouseleave", () => {
    clearTimeout(revealTimer);
    activate(pinned, false);
  });

  // Clicking or tapping a line (or its numbered marker) pins its explanation
  // and scrolls straight to it.
  code.addEventListener("click", (e) => {
    const marker = e.target.closest(".marker");
    const ln = e.target.closest(".ln");
    const box = marker ? document.getElementById(`box-${marker.dataset.box}`) : ln && boxForLine(ln);
    if (marker) e.preventDefault();
    if (!box) return;
    clearTimeout(revealTimer);
    pinned = box;
    activate(box, false);
    if (sideBySide.matches) reveal(box);
    else box.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "center" });
  });

  let frame = 0;
  const redraw = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); };
  window.addEventListener("scroll", redraw, { passive: true });
  window.addEventListener("resize", redraw);
  code.addEventListener("scroll", redraw, { passive: true });

  // Copy button. Falls back to selecting a hidden textarea when the async
  // clipboard API is unavailable (plain http, older browsers).
  const copy = document.getElementById("copy");
  const raw = document.getElementById("raw").value;
  copy.addEventListener("click", async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(raw);
      ok = true;
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = raw;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { ok = document.execCommand("copy"); } catch (e2) {}
      ta.remove();
    }
    copy.textContent = ok ? "Copied ✓" : "Copy failed — use Download";
    setTimeout(() => (copy.textContent = "Copy script"), 2000);
  });
})();
