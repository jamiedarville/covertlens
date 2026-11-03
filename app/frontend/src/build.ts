// Build flavour (CL-67). Vite replaces import.meta.env.VITE_DEMO_BUILD
// at build time, so `VITE_DEMO_BUILD=off npm run build` produces a
// non-demo build: the demo-role picker is dropped from the bundle and
// no request ever carries X-Demo-Role. The default is the demo build.
export const DEMO_BUILD: boolean = import.meta.env.VITE_DEMO_BUILD !== "off";
