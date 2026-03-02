# SEO Guide

This document covers the search engine optimization (SEO) implementation in HorizonAlerts, including metadata, structured data, sitemap, robots.txt, and social cards.

---

## Metadata Architecture

### Root Layout Metadata

The root layout (`apps/web/app/layout.tsx`) defines site-wide default metadata:

```typescript
export const metadata: Metadata = {
  title: {
    default: "Nova by Horizon | Autonomous AI Trading Bots",
    template: "%s | Nova by Horizon",
  },
  description: "Fully autonomous crypto and stock trading bots powered by AI confluence engines. 12 strategies, real-time risk management. Managed hosting or self-hosted.",
  keywords: [
    "AI trading bot", "crypto trading bot", "stock trading bot",
    "algorithmic trading", "automated trading", "trading signals",
    "trading alerts", "Kraken bot", "Coinbase bot", "options alerts"
  ],
  metadataBase: new URL(siteUrl), // process.env.PUBLIC_SITE_URL || "https://horizonsvc.com"
  openGraph: {
    type: "website",
    siteName: "Nova by Horizon",
    title: "Nova by Horizon | Autonomous AI Trading Bots",
    description: "...",
    url: siteUrl,
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: "Nova by Horizon" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Nova by Horizon | Autonomous AI Trading Bots",
    description: "...",
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
};
```

### Title Template

The `template: "%s | Nova by Horizon"` format means:
- Home page: "Nova by Horizon | Autonomous AI Trading Bots" (uses `default`)
- Pricing page: "Pricing | Nova by Horizon" (uses template with page title)
- Blog posts: "[Post Title] | Nova by Horizon"

### Per-Page Metadata

Individual pages export their own `Metadata` objects that override defaults:

**Pricing page**:
```typescript
export const metadata: Metadata = {
  title: "Pricing",
  description: "AI trading bot plans -- self-hosted from $49.99/mo or fully managed from $99.99/mo...",
  openGraph: {
    title: "Pricing | Nova by Horizon",
    description: "...",
  },
};
```

---

## JSON-LD Structured Data

### Landing Page

The home page includes SoftwareApplication structured data:

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Nova by Horizon",
  "applicationCategory": "FinanceApplication",
  "operatingSystem": "Cloud / Self-Hosted",
  "description": "Fully autonomous AI trading bot...",
  "offers": {
    "@type": "AggregateOffer",
    "lowPrice": "49.99",
    "highPrice": "249.99",
    "priceCurrency": "USD",
    "offerCount": "3"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "ratingCount": "2847"
  },
  "provider": {
    "@type": "Organization",
    "name": "Horizon Services LLC",
    "url": "https://horizonsvc.com"
  }
}
```

### Pricing Page

The pricing page includes Product structured data:

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Nova AI Trading Bot",
  "description": "Autonomous AI trading bot with 12 strategies...",
  "brand": { "@type": "Brand", "name": "Horizon Services" },
  "offers": [
    {
      "@type": "Offer",
      "name": "Self-Hosted",
      "price": "49.99",
      "priceCurrency": "USD",
      "priceValidUntil": "2027-12-31",
      "availability": "https://schema.org/InStock"
    },
    {
      "@type": "Offer",
      "name": "Pro (Managed)",
      "price": "99.99",
      "priceCurrency": "USD",
      "priceValidUntil": "2027-12-31",
      "availability": "https://schema.org/InStock"
    }
  ]
}
```

### Implementation

JSON-LD is injected via `<script type="application/ld+json">` tags using `dangerouslySetInnerHTML`:

```tsx
<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
/>
```

---

## Sitemap

### Dynamic Sitemap Generation

The sitemap is generated dynamically in `apps/web/app/sitemap.ts`:

```typescript
export default function sitemap(): MetadataRoute.Sitemap {
  const base = process.env.PUBLIC_SITE_URL || "https://horizonsvc.com";
  const routes = [
    { path: "",              priority: 1.0, changeFrequency: "weekly" },
    { path: "/pricing",      priority: 0.9, changeFrequency: "monthly" },
    { path: "/academy",      priority: 0.8, changeFrequency: "weekly" },
    { path: "/blog",         priority: 0.8, changeFrequency: "daily" },
    { path: "/trust-safety", priority: 0.5, changeFrequency: "monthly" },
    { path: "/contact",      priority: 0.5, changeFrequency: "monthly" },
    { path: "/about",        priority: 0.6, changeFrequency: "monthly" },
    { path: "/cookies",      priority: 0.3, changeFrequency: "monthly" },
    { path: "/privacy",      priority: 0.3, changeFrequency: "monthly" },
    { path: "/terms",        priority: 0.3, changeFrequency: "monthly" },
    { path: "/dmarc",        priority: 0.3, changeFrequency: "monthly" },
  ];
  // Returns array with url, lastModified, priority, changeFrequency
}
```

**Accessible at**: `https://horizonsvc.com/sitemap.xml`

### Priority Strategy

| Priority | Pages |
|---|---|
| 1.0 | Home page |
| 0.9 | Pricing |
| 0.8 | Academy, Blog |
| 0.6 | About |
| 0.5 | Contact, Trust & Safety |
| 0.3 | Legal pages (Privacy, Terms, Cookies, DMARC) |

### Not Included

The following routes are intentionally excluded from the sitemap:
- `/dashboard` -- Authenticated, private content
- `/settings` -- Authenticated, private content
- `/auth`, `/login`, `/signup` -- Auth pages
- `/onboarding` -- Authenticated flow
- `/api/*` -- API endpoints

---

## Robots.txt

### Dynamic Generation

`apps/web/app/robots.ts` generates robots.txt:

```typescript
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{
      userAgent: "*",
      allow: "/",
      disallow: ["/api/", "/dashboard", "/settings", "/auth", "/onboarding", "/login"]
    }],
    sitemap: `${base}/sitemap.xml`
  };
}
```

**Accessible at**: `https://horizonsvc.com/robots.txt`

### Disallowed Paths

| Path | Reason |
|---|---|
| `/api/` | API endpoints, not for crawling |
| `/dashboard` | Authenticated content |
| `/settings` | Authenticated content |
| `/auth` | Login/signup page |
| `/onboarding` | Authenticated flow |
| `/login` | Login redirect |

### Dashboard noindex

The dashboard layout additionally injects a `<meta name="robots" content="noindex, nofollow">` tag via JavaScript to double-ensure search engines do not index authenticated pages.

---

## Open Graph & Twitter Cards

### Default Configuration

Set in the root layout metadata:

**Open Graph**:
- Type: `website`
- Site Name: `Nova by Horizon`
- Image: `/og-image.png` (1200x630)
- URL: Site URL

**Twitter**:
- Card: `summary_large_image`
- Image: `/og-image.png`

### Per-Page Overrides

Individual pages can override OG metadata for social sharing. The pricing page, for example, sets custom OG title and description specific to pricing content.

### Image Requirements

The OG image (`/og-image.png`) should be:
- **Dimensions**: 1200x630 pixels
- **Format**: PNG
- **Location**: `apps/web/public/og-image.png`
- **Alt text**: "Nova by Horizon -- Autonomous AI Trading Bots"

---

## Page Structure Best Practices

### Semantic HTML

All pages use semantic heading hierarchy:
- `<h1>` -- Main page title (one per page)
- `<h2>` -- Section headings
- `<h3>` -- Subsection headings
- `<h4>` -- Footer column headings

### Link Structure

The footer provides comprehensive internal linking:
- **Platform**: Pricing, Dashboard, Settings, Login
- **Resources**: Academy, Blog, Support
- **Legal & Trust**: Privacy, Terms, Cookies, Trust & Safety, Email Security

### External Links

Exchange names and supported markets are listed but not linked externally. This keeps link equity within the site.

---

## Analytics Integration

### PostHog

PostHog analytics is integrated via the `Analytics` component:

```
NEXT_PUBLIC_POSTHOG_KEY -- PostHog project API key
NEXT_PUBLIC_POSTHOG_HOST -- PostHog host (default: https://app.posthog.com)
```

The CSP allows connections to `https://app.posthog.com` and `https://us.i.posthog.com`.

---

## Performance Considerations

### Next.js App Router

The App Router automatically:
- Server-renders pages for SEO
- Streams HTML for fast Time to First Byte
- Prefetches links for instant navigation
- Generates static sitemap.xml and robots.txt

### Content Loading

- Academy and blog content is loaded from MDX files in the `/content` directory
- Dynamic routes use `[slug]` pattern for individual articles
- Content is server-rendered for full SEO indexing

---

## Checklist for New Pages

When adding a new public page:

1. Export `Metadata` with title, description, and OpenGraph data
2. Add the route to `sitemap.ts` with appropriate priority and changeFrequency
3. Ensure the route is NOT in the robots.txt disallow list (unless it should be)
4. Use semantic HTML with proper heading hierarchy
5. Add internal links to/from the new page
6. Consider adding JSON-LD structured data if applicable
7. Test with Google Rich Results Test and Open Graph debugger

---

*Last updated: March 2026*
