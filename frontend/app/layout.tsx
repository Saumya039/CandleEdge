import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stratagy · NSE F&O options workstation",
  description: "Decision-support and paper-trading workstation for buying NSE index/stock options. No live orders.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0a0e13" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
