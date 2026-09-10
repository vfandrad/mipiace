import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import logoMiPiace from "@/assets/logo-mipiace.png";

function preloadLogo(src: string) {
  return new Promise<void>((resolve) => {
    const img = new Image();
    img.src = src;

    if (img.complete) {
      resolve();
      return;
    }

    img.onload = () => resolve();
    img.onerror = () => resolve();
  });
}

const root = createRoot(document.getElementById("root")!);

preloadLogo(logoMiPiace).finally(() => {
  root.render(<App />);
});
