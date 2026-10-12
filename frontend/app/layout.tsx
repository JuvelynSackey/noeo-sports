import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { Nav } from "@/components/Nav";
import { Disclaimer } from "@/components/Disclaimer";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Noeo Sports",
  description: "The intelligence of the game, quantified.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-slate-950 text-slate-100">
        <AuthProvider>
          <Nav />
          <main className="flex flex-1 flex-col">{children}</main>
          <footer className="border-t border-slate-800 px-4 py-4">
            <div className="mx-auto max-w-6xl">
              <Disclaimer />
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
