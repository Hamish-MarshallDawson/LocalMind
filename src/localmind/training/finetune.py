"""
Fine-tune Qwen3-VL-8B with Unsloth QLoRA on custom document Q&A data.

Usage:
    python -m localmind.training.finetune \
        --dataset data/training/qa_pairs.jsonl \
        --output models/qwen3-vl-finetuned \
        --epochs 3

Training data format (JSONL):
    {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
    {"messages": [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "..."}]}, {"role": "assistant", "content": "..."}], "images": ["path/to/image.png"]}
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def create_training_args(output_dir: str, epochs: int, batch_size: int, lr: float):
    from trl import SFTConfig

    return SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        learning_rate=lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        bf16=True,
        logging_steps=10,
        save_strategy="epoch",
        optim="adamw_8bit",
        seed=42,
        max_seq_length=2048,
        dataset_text_field="",
        dataset_kwargs={"skip_prepare_dataset": True},
        remove_unused_columns=False,
    )


def load_model(model_name: str):
    from unsloth import FastVisionModel

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name,
        load_in_4bit=True,
        use_gradient_checkpointing="unsloth",
    )

    model = FastVisionModel.get_peft_model(
        model,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        use_rslora=False,
        bias="none",
    )

    return model, tokenizer


def load_dataset(dataset_path: str, tokenizer):
    import json
    from datasets import Dataset
    from PIL import Image

    records = []
    with open(dataset_path) as f:
        for line in f:
            record = json.loads(line.strip())
            records.append(record)

    def format_example(example):
        messages = example["messages"]
        images = []

        if "images" in example and example["images"]:
            for img_path in example["images"]:
                images.append(Image.open(img_path).convert("RGB"))

        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )

        return {"text": text, "images": images}

    dataset = Dataset.from_list(records)
    dataset = dataset.map(format_example, remove_columns=dataset.column_names)
    return dataset


def train(
    model_name: str = "Qwen/Qwen3-VL-8B-Instruct",
    dataset_path: str = "data/training/qa_pairs.jsonl",
    output_dir: str = "models/qwen3-vl-finetuned",
    epochs: int = 3,
    batch_size: int = 1,
    lr: float = 2e-4,
):
    from trl import SFTTrainer

    logger.info("Loading model: %s", model_name)
    model, tokenizer = load_model(model_name)

    logger.info("Loading dataset: %s", dataset_path)
    dataset = load_dataset(dataset_path, tokenizer)
    logger.info("Dataset size: %d examples", len(dataset))

    training_args = create_training_args(output_dir, epochs, batch_size, lr)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    logger.info("Starting training...")
    trainer.train()

    logger.info("Saving model to: %s", output_dir)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    logger.info("Training complete.")
    return output_dir


def export_gguf(model_dir: str, quantization: str = "q4_k_m"):
    from unsloth import FastVisionModel

    logger.info("Exporting to GGUF: %s (quant: %s)", model_dir, quantization)
    model, tokenizer = FastVisionModel.from_pretrained(model_dir, load_in_4bit=True)
    model.save_pretrained_gguf(
        f"{model_dir}-gguf",
        tokenizer,
        quantization_method=quantization,
    )
    logger.info("GGUF export complete: %s-gguf", model_dir)


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen3-VL with Unsloth")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--dataset", required=True, help="Path to JSONL training data")
    parser.add_argument("--output", default="models/qwen3-vl-finetuned")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--export-gguf", action="store_true", help="Also export to GGUF")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    output = train(
        model_name=args.model,
        dataset_path=args.dataset,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )

    if args.export_gguf:
        export_gguf(output)


if __name__ == "__main__":
    main()
