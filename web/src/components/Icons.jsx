// 介面用的線條圖示（Lucide 風格），全部 inline SVG、跟著文字顏色（currentColor）走。
// 刻意不用 emoji 當圖示：emoji 在各平台長得不一樣、也無法跟著主題變色。
function Svg({ size = 22, strokeWidth = 1.8, children }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const RadarIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <circle cx="12" cy="12" r="5" />
    <path d="M12 12l6.5-5.5" />
  </Svg>
);

export const CompassIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z" />
  </Svg>
);

export const SearchIcon = (p) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7.5" />
    <path d="m20.5 20.5-4.2-4.2" />
  </Svg>
);

export const ThumbUpIcon = (p) => (
  <Svg {...p}>
    <path d="M7 10v12" />
    <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
  </Svg>
);

export const CloseIcon = (p) => (
  <Svg {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Svg>
);

export const ExternalIcon = (p) => (
  <Svg size={12} strokeWidth={2} {...p}>
    <path d="M7 17 17 7M8 7h9v9" />
  </Svg>
);

export const RepoIcon = (p) => (
  <Svg size={13} strokeWidth={2} {...p}>
    <path d="M6 3v12" />
    <circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" />
    <path d="M18 9a9 9 0 0 1-9 9" />
  </Svg>
);

export const PaperIcon = (p) => (
  <Svg size={13} strokeWidth={2} {...p}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
    <path d="M14 2v5h5M16 13H8M16 17H8" />
  </Svg>
);

export const ModelIcon = (p) => (
  <Svg size={13} strokeWidth={2} {...p}>
    <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
    <path d="m3.3 7 8.7 5 8.7-5M12 22V12" />
  </Svg>
);

export const DatasetIcon = (p) => (
  <Svg size={13} strokeWidth={2} {...p}>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5v14a9 3 0 0 0 18 0V5" />
    <path d="M3 12a9 3 0 0 0 18 0" />
  </Svg>
);

// 品牌標誌：兩圈雷達加一道掃描線，琥珀色的點是「偵測到的訊號」。
export function LogoMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <circle cx="14" cy="14" r="12.5" stroke="var(--primary)" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="7.5" stroke="var(--primary)" strokeWidth="1.5" strokeOpacity="0.55" />
      <path d="M14 14 L23.5 6.5" stroke="var(--primary)" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="19.5" cy="9.6" r="2.4" fill="var(--accent)" />
    </svg>
  );
}
