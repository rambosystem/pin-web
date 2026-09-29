import { useEffect, useRef, useState } from "react";

/**
 * Pacing model: proportional control on the backlog.
 *
 *   rate = clamp(backlog / LAG_SECONDS, MIN_CPS, MAX_CPS)
 *
 * With a steady incoming rate r the backlog settles at r * LAG_SECONDS and the
 * display reveals at exactly r, so the text trails the network by a constant
 * ~LAG_SECONDS regardless of how fast the model is. A burst (several hundred
 * characters in one chunk) is spread over roughly LAG_SECONDS instead of
 * appearing at once, and a short network gap is bridged by the backlog
 * draining smoothly (the rate decays, it does not stop dead). MIN_CPS keeps
 * the tail finishing at a perceptible typing speed once the stream ends;
 * MAX_CPS caps how far a single frame may jump.
 */
const LAG_SECONDS = 1.0;
const MIN_CPS = 20;
const MAX_CPS = 400;

type TextMap = Record<string, string>;

/** Avoid cutting a surrogate pair (emoji etc.) in half. */
function safeCut(s: string, end: number): number {
  if (end <= 0 || end >= s.length) return Math.max(0, Math.min(end, s.length));
  const code = s.charCodeAt(end - 1);
  return code >= 0xd800 && code <= 0xdbff ? end + 1 : end;
}

/**
 * Smooth a set of streamed strings into a steady typewriter reveal.
 *
 * Network chunks arrive in bursts (several characters, sometimes several
 * hundred, at once). This hook treats each incoming value as a *target* and
 * advances the displayed text toward it on requestAnimationFrame at a rate
 * that adapts to the backlog, so the eye sees continuous typing rather than
 * jumps. A target that is not an extension of what is shown (reset, error,
 * different content) snaps immediately.
 *
 * Returns the text to render for each key plus `settled`, true once every
 * displayed value has caught up with its target.
 */
export function useSmoothText(target: TextMap): { displayed: TextMap; settled: boolean } {
  const [displayed, setDisplayed] = useState<TextMap>({});
  const targetRef = useRef(target);
  targetRef.current = target;
  const displayedRef = useRef<TextMap>({});
  const carryRef = useRef<Record<string, number>>({});
  const rafRef = useRef(0);

  useEffect(() => {
    if (rafRef.current) return; // loop already running; it reads targetRef
    let last = performance.now();

    const tick = (now: number) => {
      // Browsers pause requestAnimationFrame in background tabs. If we were
      // frozen for a while, the user was not watching: snap to the target
      // instead of replaying a long backlog when they come back.
      const frozen = now - last > 1000;
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      if (frozen) {
        const tgt = { ...targetRef.current };
        displayedRef.current = tgt;
        carryRef.current = {};
        setDisplayed(tgt);
        rafRef.current = 0;
        return;
      }
      const tgt = targetRef.current;
      const cur = displayedRef.current;
      const next: TextMap = { ...cur };
      let changed = false;
      let pending = false;

      for (const k of Object.keys(cur)) {
        if (!(k in tgt)) {
          delete next[k];
          delete carryRef.current[k];
          changed = true;
        }
      }
      for (const k of Object.keys(tgt)) {
        const t = tgt[k];
        const d = next[k] ?? "";
        if (!t.startsWith(d)) {
          next[k] = t; // not an append: snap
          changed = true;
          continue;
        }
        const backlog = t.length - d.length;
        if (backlog <= 0) continue;
        const rate = Math.min(MAX_CPS, Math.max(MIN_CPS, backlog / LAG_SECONDS));
        const carry = (carryRef.current[k] ?? 0) + rate * dt;
        const n = Math.floor(carry);
        carryRef.current[k] = carry - n;
        if (n > 0) {
          next[k] = t.slice(0, safeCut(t, d.length + n));
          changed = true;
        }
        if (next[k].length < t.length) pending = true;
      }

      if (changed) {
        displayedRef.current = next;
        setDisplayed(next);
      }
      if (pending) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = 0;
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    };
    // Re-run whenever the target object changes so a stopped loop restarts.
  }, [target]);

  const settled = Object.keys(target).every((k) => displayed[k] === target[k])
    && Object.keys(displayed).every((k) => k in target);
  return { displayed, settled };
}
