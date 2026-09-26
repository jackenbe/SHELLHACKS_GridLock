import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./app";

const rootElement = document.getElementById("root");
const root = createRoot(rootElement);

root.render(
  <StrictMode>
    <h1>Sperry Tech
        GridLock
    </h1>
    <App />
  </StrictMode>
);
