# Product

## Register

product

## Users

Dr. Osoro, a Nairobi-based landlord, is the primary user. He works in the app daily on a desktop monitor, in his office, as a power user. He owns and operates a portfolio of buildings, units, and tenants — the app is his private operating system for the business.

Secondary context: rent collection runs through M-Pesa (Daraja); receipts and statements go out by email; tenants pay in KSh. The job to be done is "see what's happening in my portfolio today, and act on what needs me." Most sessions are short and goal-oriented: confirm a payment, message a tenant, review the month, export a statement.

## Product Purpose

A private property suite for one owner, not a multi-tenant SaaS. Success looks like Dr. Osoro opening the app and immediately knowing what needs his attention this morning — who paid, who's overdue, which units turn over, what the month looks like. Friction is the enemy: every screen should answer one or two questions and let him act on them without thinking.

The product is not trying to replace a property manager. It is trying to make running the portfolio feel composed, considered, and quietly luxurious — closer to managing a personal art collection than running enterprise software.

## Brand Personality

Three words: **editorial, considered, warm.**

Voice is the voice of a discreet private bank or a fine hotel: confident, precise, low on adjectives, never chirpy. Numbers are treated with care; money is dignified, not gamified. The interface should feel like Dr. Osoro's office — quiet, well-lit, generous, made of warm materials. Joy comes from craft and restraint, not from confetti or gradients.

Tone in copy: complete sentences in headers and empty states; short, declarative microcopy elsewhere. No exclamation marks. No "Oops!" No "Let's get started!" Respect the reader.

## Anti-references

Explicitly NOT:

- **Generic SaaS cloud-software aesthetic.** QuickBooks, Xero, AppFolio, Buildium, Yardi. Blue gradients, sterile drop shadows, dashboard cards repeated nine times in a grid, "Welcome back, Sharon! 🎉".
- **Crypto / fintech loudness.** Neon on black, animated gradient backgrounds, gambling-app energy.
- **Notion-style playfulness.** Illustrated empty states, mascots, big rounded everything, emoji-led navigation.
- **The hero-metric template.** Four identical KPI cards with a sparkline and a percentage delta. This is the default; it is also the cliché.

The reference is **luxury real estate publishing**: Sotheby's International Realty, The Modern House, Aman, Aesop. Serif display typography, monochromatic warm palettes, generous whitespace, photography when used at all is the protagonist, not decoration.

## Design Principles

1. **Editorial restraint.** Whitespace, typography, and small radii do more work than effects. When in doubt, remove. Cards are not the answer; structured pages are.

2. **Warm, never corporate.** Every neutral tints toward espresso or cream. No cold grays, no SaaS blue, no `#000` or `#fff`. The palette is amber gold, aged gold, muted rust, warm taupe, espresso — already established and load-bearing.

3. **Numbers are jewelry.** Financial figures, dates, and counts earn the display serif (Fraunces). Money is rendered with care: tabular numerals, currency in the right register, never with a percentage badge in a contrasting color block.

4. **Hierarchy through type and space, not boxes.** Sections separate via scale, leading, and whitespace before they separate via card walls. Nested cards are always wrong. One surface per concept.

5. **Practice luxury.** What a $5M property listing feels like on Sotheby's: spacious, sure, low-friction. Apply that posture to every screen, including the boring ones. A late-payment list deserves the same respect as a hero page.

## Accessibility & Inclusion

- **WCAG 2.1 AA** as the baseline target. Particular attention to text-on-cream contrast: `ink-500` on `bg-canvas-alt` is a known-edge case that needs verification per component.
- `prefers-reduced-motion` already honored in `index.css` — keep it honored. Any new animation must collapse gracefully.
- Numeric tables use tabular numerals (`font-feature-settings: "tnum"` where applicable) so columns align for fast scanning.
- Focus rings are visible and on-brand (amber gold, 2px). Don't suppress them for aesthetics.
- Single primary user; no multi-language requirement today. Currency is KSh, dates are EAT.
