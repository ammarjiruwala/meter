import { MeterLoader } from "@/components/MeterLoader";

/**
 * Shown the instant someone navigates here, while the page's ten queries stream.
 *
 * The route is `force-dynamic` against a database in another region, so first paint is
 * around five seconds. Without this the button reads as broken and people click it twice.
 */
export default function Loading() {
  return <MeterLoader />;
}
