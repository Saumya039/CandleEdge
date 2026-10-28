/** The browser only talks to this origin; /api is proxied to the backend so no CORS or backend URL is exposed. */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
/** Static recorded-replay demo (NEXT_PUBLIC_DEMO=1): no backend, relative asset paths so it can be hosted under any path. */
const demo = process.env.NEXT_PUBLIC_DEMO === "1";

/** @type {import('next').NextConfig} */
const nextConfig = demo
  ? { reactStrictMode: true, poweredByHeader: false, output: "export", assetPrefix: ".", images: { unoptimized: true } }
  : {
      reactStrictMode: true,
      poweredByHeader: false,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
      async headers() {
        return [
          {
            source: "/:path*",
            headers: [
              { key: "X-Content-Type-Options", value: "nosniff" },
              { key: "X-Frame-Options", value: "DENY" },
              { key: "Referrer-Policy", value: "no-referrer" },
            ],
          },
        ];
      },
    };
export default nextConfig;
