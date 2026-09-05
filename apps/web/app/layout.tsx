import type { Metadata } from "next";
import { Inter, Geist_Mono } from "next/font/google";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import "./globals.css";

// Inter substitutes for the design reference's Aeonik/AeonikFono (both
// paid typefaces) - same geometric-humanist, weight-400-default character,
// per the reference doc's own listed substitute.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RiskPilot",
  description: "Cost-aware fraud decisioning and policy simulation console.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-obsidian font-sans text-white">
        <TooltipPrimitive.Provider delayDuration={200}>{children}</TooltipPrimitive.Provider>
      </body>
    </html>
  );
}
