import js            from "@eslint/js";
import tsPlugin      from "@typescript-eslint/eslint-plugin";
import tsParser      from "@typescript-eslint/parser";
import reactHooks    from "eslint-plugin-react-hooks";
import reactRefresh  from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist", "node_modules", "coverage"] },

  // ── Base JS recommended ────────────────────────────────────────────────────
  js.configs.recommended,

  // ── TypeScript files ───────────────────────────────────────────────────────
  {
    files: ["src/**/*.{ts,tsx}", "tests/**/*.ts"],
    languageOptions: {
      parser:        tsParser,
      parserOptions: {
        project:     "./tsconfig.json",
        ecmaVersion: 2020,
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks":        reactHooks,
      "react-refresh":      reactRefresh,
    },
    rules: {
      // ── TypeScript strict ────────────────────────────────────────────────
      ...tsPlugin.configs["strict-type-checked"].rules,
      "@typescript-eslint/no-explicit-any":          "error",
      "@typescript-eslint/explicit-function-return-type": "off", // inferred is fine
      "@typescript-eslint/no-non-null-assertion":    "error",
      "@typescript-eslint/consistent-type-imports":  ["error", { prefer: "type-imports" }],

      // ── React hooks ──────────────────────────────────────────────────────
      ...reactHooks.configs.recommended.rules,

      // ── React refresh (Vite HMR) ─────────────────────────────────────────
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // ── General quality ──────────────────────────────────────────────────
      "no-console":           ["warn", { allow: ["warn", "error"] }],
      "no-debugger":          "error",
      "prefer-const":         "error",
      "no-var":               "error",
      "eqeqeq":               ["error", "always"],
      "no-unused-expressions":"error",
    },
  },

  // ── Test files — relax some rules ─────────────────────────────────────────
  {
    files: ["tests/**/*.ts"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "no-console":                         "off",
    },
  },
];
