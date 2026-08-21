const LABELS = {
  arxiv: "arXiv",
  github: "GitHub",
  huggingface_models: "HF Model",
  huggingface_datasets: "HF Dataset",
};

export default function SourceBadge({ source }) {
  return <span className={`badge badge-${source}`}>{LABELS[source] || source}</span>;
}
