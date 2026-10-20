import { BRAND_LOGO } from "@/lib/brand";

/**
 * The round logo mark. It is decorative (the product name is always written next to it), so it has no alt text.
 * `size` is in pixels.
 */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    // A plain <img>: a small fixed picture from /public, so there is nothing for next/image to optimise.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={BRAND_LOGO} alt="" width={size} height={size} className="shrink-0" />
  );
}
