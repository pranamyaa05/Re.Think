# Re.think() — design brief

## Direction
A book-first, calm learner-growth landing page: motivating and thoughtful rather than exam-like or intensely academic. Make books, pages, reading, thoughtful explanations, and reflective learning the dominant visual and editorial language. Keep computers and competitive metrics present as the subject being learned, not as the page's aesthetic center. Use the user's supplied book-wheel photograph as the hero's main visual.

## Design movement
Contemporary independent-bookshop editorial meets a gentle learning companion: parchment-like page layouts, generous margins, bookish serif typography, warm paper and ink, softly layered cards, a literary photographic hero, and only restrained developer-tool cues.

## Core principles
- Progress over pressure; encourage small, repeatable steps.
- Let reading, curiosity, and reflective explanations lead the narrative; make coding the material the learner is reading about.
- Keep product preview useful but secondary, with all metrics explicitly marked as sample/demo data.
- Keep coding approachable: warm guidance, not competitive bravado.
- Let whitespace, hierarchy, and reassuring copy carry the design.

## Color philosophy
Use warm book-paper and cream as the dominant canvas, deep bottle/ink green for type, muted walnut and soft copper as small page-edge accents, and quiet sea-glass as a secondary restorative note. Keep the CTA accent warm rather than electric. Preserve comfortable contrast and avoid the dark, neon-heavy esports aesthetic.

## Layout paradigm
A narrow centered navigation; a book-first split hero with the learner-facing promise and a large supplied book-wheel photograph; a reading and explanation section; a coach preview styled like a thoughtful margin note; a literary quote interlude; then the smaller unified LeetCode/Codeforces demo dashboard and leaderboard. Finish with a warm repeated CTA and concise footer. Collapse to a clear single column on mobile.

## Signature elements
- The user's book-wheel artwork as a large, editorial hero visual.
- Re.think() wordmark with a custom minimal rising-sun/open-notebook symbol.
- Small “not live data” labels on every illustrative metric cluster.
- Light route-map/step motif, progress dots, small pill badges, and a hand-drawn-feeling quote treatment.
- A deliberately calm dashboard rather than a gamified, leaderboard-dominant screen.

## Interaction philosophy
Navigation links scroll to page sections. CTA buttons lead to the in-page reading and coaching sections rather than claiming sign-up is wired. Keep all navigation and controls keyboard accessible. No fake account-sync controls or false live-data affordances. Add playful, polished, mouse-only letter bounce on selected short labels, subtle cursor attraction and 3D perspective on cards, pointer-following light, and a very soft trailing grid in the hero. The grid and tilt stay decorative and do not obscure the book photo or affect page readability. Disable cursor-only motion on touch and respect reduced-motion preferences.

## Animation
The analyzed reference is a single, type-led portfolio drawn through a WebGL scrolling canvas, with a lagged custom cursor, GSAP ScrollSmoother/ScrollTrigger, SplitText choreography, and playful hover-revealed media. Borrow the rhythm, not its identity or implementation: preserve Re.think()'s accessible HTML, book-first composition, and gentle editorial mood. Use small staggered letter dances on hover, cursor-responsive light and grid drift in the hero, and low-angle 3D tilt plus realistic shadow lift on learning cards. Keep scroll reveals quiet and brief; do not add scroll-jacking or heavy WebGL. On touch, remove cursor-specific motion; with `prefers-reduced-motion`, show content immediately and disable looping/tilt.

## Typography system
Replace the generic geometric sans feel with a warm, humanist editorial pair: Karla for readable body and interface copy; Lora for literary headings, quote moments, and accent phrases. Preserve natural sentence casing and generous line height; use uppercase only for restrained bookish labels. Keep monospaced text rare, limited to literal code references. Load both as normal text fonts, with humane system/serif fallbacks.

## Daily quote
Show one original Re.think() reflection as a daily margin note. Choose consistently from a curated local collection based on the visitor's local calendar date, refresh at the next local midnight while a page stays open, and offer a small “another line” control. No external API or live-generation claim.

## Brand essence
A thoughtful coding companion that helps learners notice how far they have come and find the next useful step.

## Brand voice
Warm, direct, curious, non-judgmental, and quietly optimistic. Prefer “try again,” “one good question,” and “your pace” to grind, hustle, or mastery claims.

## Wordmark/logo
A custom flat square icon: rising sun over an open notebook, using a clear silhouette and negative space. Pair it with the exact text wordmark `Re.think()` in the website UI. Reuse the icon for favicon/project identity.

## Signature brand color
Sea-glass teal, supported by a soft mist background and a warm citron/lime accent.

## Asset placements
- Custom 1:1 project mark in the header and favicon.
- The supplied book-wheel image in the hero as the main visual focus.
- Keep the quote interlude typographic and warm; do not compete with the book-wheel hero using another scenic image.
