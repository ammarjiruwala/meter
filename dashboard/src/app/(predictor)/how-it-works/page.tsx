import { PredictorPage } from "@/components/predictor/PredictorPage";

/**
 * The predictive-engine explainer at `/how-it-works`.
 *
 * Static shell, interactive client scene. Reads no database. Every number in it
 * traces back to `predictor/DESIGN.md`.
 */
export default function Page() {
  return <PredictorPage />;
}
