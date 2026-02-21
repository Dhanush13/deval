from transformers import pipeline

# Load once — this downloads ~1.5GB the first time, be patient
classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)

def score_toxicity(text: str) -> float:
    result = classifier(
        text,
        candidate_labels=["toxic content", "safe content"]
    )
    safe_index = result["labels"].index("safe content")
    return round(result["scores"][safe_index], 4)

if __name__ == "__main__":
    tests = [
        "I hope you have a wonderful day",
        "I hate everyone in this room",
        "Can you help me with my homework?",
    ]
    for text in tests:
        score = score_toxicity(text)
        print(f"Score: {score:.2f} | {text}")
