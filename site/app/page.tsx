import { Demo } from "@/components/Demo";
import { Features } from "@/components/Features";
import { Footer } from "@/components/Footer";
import { Hero } from "@/components/Hero";
import { Install } from "@/components/Install";
import { LoopStory } from "@/components/LoopStory";
import { Nav } from "@/components/Nav";

export default function HomePage() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Nav />
      <main id="main">
        <Hero />
        <LoopStory />
        <Features />
        <Demo />
        <Install />
      </main>
      <Footer />
    </>
  );
}
