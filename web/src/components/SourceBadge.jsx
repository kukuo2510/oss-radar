const LABELS = {
  arxiv: "論文",
  github: "程式庫",
  huggingface_models: "模型",
  huggingface_datasets: "資料集",
};

export default function SourceBadge({ source }) {
  return <span className={`badge badge-${source}`}>{LABELS[source] || source}</span>;
}
