import { DatasetIcon, ModelIcon, PaperIcon, RepoIcon } from "./Icons";

// 來源用「文字＋圖示」區分，不只靠顏色（色弱的人也分得出來）。
const SOURCES = {
  arxiv: { label: "arXiv 論文", Icon: PaperIcon },
  github: { label: "GitHub 專案", Icon: RepoIcon },
  huggingface_models: { label: "HF 模型", Icon: ModelIcon },
  huggingface_datasets: { label: "HF 資料集", Icon: DatasetIcon },
};

export default function SourceBadge({ source }) {
  const s = SOURCES[source];
  return (
    <span className="badge">
      {s && <s.Icon />}
      {s ? s.label : source}
    </span>
  );
}
