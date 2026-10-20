// White-label: the product name and logo shown to clients. Set NEXT_PUBLIC_BRAND_NAME / NEXT_PUBLIC_BRAND_LOGO in .env.local.
export const BRAND_NAME = process.env.NEXT_PUBLIC_BRAND_NAME || "Iris";
// The round logo mark: a picture in /public, shown next to the name (sidebar, login page, admin).
// Raise ?v= whenever the picture changes, so browsers don't keep showing the old one from their cache.
export const BRAND_LOGO = process.env.NEXT_PUBLIC_BRAND_LOGO || "/brand/iris-mark.png?v=2";
