# Dashboard + Widget (TypeScript migration of lobitab/lobipanel)

This project contains:

- `src/` — modern TypeScript implementation (`DashboardTabs`, `DashboardView`, `Widget`, and a simple resizable grid layout).
- `demo/` — a *working* no-build demo (ES module JavaScript) that you can run in a browser.

## Run the demo (no build)

Because the demo uses ES modules, serve it with any static server:

```bash
cd demo
python3 -m http.server 8080
# open http://localhost:8080
```

## Build the TypeScript (optional)

If you want to compile the TypeScript:

```bash
npm init -y
npm i -D typescript
npx tsc --init
# set "rootDir": "src", "outDir": "dist", "target": "ES2022", "module": "ES2022"
npx tsc
```

Then wire up your app entrypoint in your own bundler (Vite/esbuild/Webpack), or just use the demo JS as a reference.
