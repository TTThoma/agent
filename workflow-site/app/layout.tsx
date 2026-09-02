import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Agent Workflow — From Idea to Review',
  description:
    'An inspectable, reusable engineering workflow with explicit agent goals, inputs, outputs, skills, and gates.',
  openGraph: {
    title: 'Agent Workflow',
    description: 'From rough idea to review-ready change.',
    images: [{ url: '/og.png', width: 1731, height: 909, alt: 'Agent Workflow — From rough idea to review-ready change.' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Agent Workflow',
    description: 'From rough idea to review-ready change.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
