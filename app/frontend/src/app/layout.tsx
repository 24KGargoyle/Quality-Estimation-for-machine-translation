import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import NavBar from "@/components/NavBar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Meeting Assistant | Everforth Quinnox",
  icons: { icon: "/brand/everforth-quinnox-icon.png", apple: "/brand/everforth-quinnox-icon.png" },
  description: "Agentic Microsoft Teams Meeting Intelligence & Collaboration Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-neutral-50 text-neutral-900">
        <AuthProvider>
          <NavBar />
          <main id="main-content" className="app-main flex-1" tabIndex={-1}>{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
