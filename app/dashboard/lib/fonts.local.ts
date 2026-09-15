import localFont from 'next/font/local';

// Local builds never download Google Fonts.
export const figtreeFont = { className: 'agentops-local-font', variable: '' };
export const nasalizationFont = localFont({
  src: '../public/font/nasalization/nasalization-rg.otf',
  variable: '--font-nasalization',
});
