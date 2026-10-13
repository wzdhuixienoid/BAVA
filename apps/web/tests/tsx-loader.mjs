import { existsSync, readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";
// Compile the real TSX components using the existing TypeScript dependency.
const webRoot = fileURLToPath(new URL("../", import.meta.url));
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "next/link") return nextResolve("next/link.js", context);
    const base = specifier.startsWith("@/") ? pathToFileURL(`${webRoot}${specifier.slice(2)}`).href
      : specifier.startsWith(".") && context.parentURL ? new URL(specifier, context.parentURL).href : null;
    if (base && base.startsWith("file:")) {
      for (const extension of [".tsx", ".ts"]) {
        if (existsSync(fileURLToPath(base + extension))) return nextResolve(base + extension, context);
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith("/package.json")) return {
      format: "module", shortCircuit: true,
      source: `export default ${readFileSync(new URL(url), "utf8")};`,
    };
    if (url.endsWith(".tsx")) return {
      format: "module", shortCircuit: true,
      source: ts.transpileModule(readFileSync(new URL(url), "utf8"), {
        compilerOptions: { target: ts.ScriptTarget.ES2017, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
      }).outputText,
    };
    return nextLoad(url, context);
  },
});
