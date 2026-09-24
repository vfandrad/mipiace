import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Sem pré-carregamento de logo: ele antes bloqueava o primeiro render esperando
// um PNG importado pelo bundler. Hoje a marca vem de `VITE_STORE_LOGO_URL`
// (ou é só o nome da loja, em texto), então não há imagem crítica para esperar.
createRoot(document.getElementById("root")!).render(<App />);
