import { writable, derived } from "svelte/store";

// Scroll progress 0..1 (used by ScrollDriver and HUD)
export const scrollProgress = writable<number>(0);

// Breakpoint for mobile (matches --breakpoint-mobile in hud.css)
export const MOBILE_BREAKPOINT = 768;

// Inner width for responsive layout
export const innerWidth = writable<number>(typeof window !== "undefined" ? window.innerWidth : 1024);

// True when viewport is below mobile breakpoint
export const isMobile = derived(innerWidth, ($w) => $w < MOBILE_BREAKPOINT);

// When true, Upload will open the run list drawer on next show (used when navigating back on mobile)
export const openRunListOnUpload = writable<boolean>(false);
