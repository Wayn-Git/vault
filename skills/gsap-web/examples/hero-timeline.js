/**
 * hero-timeline.js — complete, runnable GSAP hero entrance.
 *
 * Markup expected:
 *   <section class="hero">
 *     <p class="hero__eyebrow">EYEBROW</p>
 *     <h1 class="hero__title">Big bold headline that wraps</h1>
 *     <p class="hero__sub">Supporting copy.</p>
 *     <div class="hero__actions"><a class="btn">Primary</a><a class="btn btn--ghost">Secondary</a></div>
 *     <img class="hero__art" src="art.svg" alt="" />
 *   </section>
 *
 * CSS prerequisite: each split line wrapper needs overflow:hidden for the mask reveal:
 *   .hero__title .line { overflow: hidden; }
 *
 * Install:  npm i gsap @gsap/react
 */

import gsap from "gsap";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(SplitText);

export function playHeroIntro(root = document) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const q = gsap.utils.selector(root);

  // Reduced motion: reveal everything instantly, no animation.
  if (reduceMotion) {
    gsap.set(q(".hero__eyebrow, .hero__sub, .hero__actions, .hero__art"), { autoAlpha: 1 });
    gsap.set(q(".hero__title"), { autoAlpha: 1 });
    return Promise.resolve();
  }

  // Wait for fonts so SplitText computes correct line breaks.
  return document.fonts.ready.then(() => {
    const titleEl = q(".hero__title")[0];
    const split = new SplitText(titleEl, {
      type: "lines",
      linesClass: "line",
      autoSplit: true, // GSAP 3.13+: re-split on resize/font swap
    });

    // Hidden start state (prevents flash of unstyled content).
    gsap.set(q(".hero__eyebrow, .hero__sub, .hero__actions, .hero__art"), { autoAlpha: 0 });
    gsap.set(titleEl, { autoAlpha: 1 });

    const tl = gsap.timeline({
      defaults: { ease: "power3.out", duration: 0.8 },
      onComplete: () => split.revert(), // restore clean DOM once done (optional)
    });

    tl.from(".hero__eyebrow", { y: 16, autoAlpha: 0, duration: 0.5 })
      .from(split.lines, { yPercent: 110, stagger: 0.12, duration: 0.9, ease: "power4.out" }, "-=0.2")
      .from(".hero__sub", { y: 20, autoAlpha: 0 }, "-=0.6")
      .from(".hero__actions .btn", { y: 12, autoAlpha: 0, stagger: 0.1, duration: 0.5 }, "-=0.4")
      .from(".hero__art", { scale: 0.92, autoAlpha: 0, ease: "back.out(1.4)", duration: 1.1 }, "<0.1");

    return tl;
  });
}

// Auto-run on DOM ready when imported directly in a page.
if (typeof window !== "undefined" && document.querySelector(".hero")) {
  if (document.readyState !== "loading") playHeroIntro();
  else document.addEventListener("DOMContentLoaded", () => playHeroIntro());
}
