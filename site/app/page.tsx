import { FeatureBento } from "@/components/home/feature-bento";
import { DemoSlot } from "@/components/home/demo-slot";
import { Hero } from "@/components/home/hero";
import { ModelPicker } from "@/components/home/model-picker";
import { Comparison, Faq, FinalCta, HowItWorks, Integrations, Safety } from "@/components/home/sections";
import { pageMeta } from "@/lib/metadata";
import { DESCRIPTION } from "@/lib/site";

export const metadata = pageMeta("Swag Bot — done only when the evidence agrees", DESCRIPTION, "/", true);

export default function HomePage() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <FeatureBento />
      <ModelPicker />
      <Safety />
      <Integrations />
      <Comparison />
      <DemoSlot />
      <Faq />
      <FinalCta />
    </>
  );
}
