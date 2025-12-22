#!/usr/bin/env python3
"""Quick test to verify scoring methods are real."""

print("=" * 50)
print("SCORING VERIFICATION TEST")
print("=" * 50)

# Check semantic scoring
print("\n1. SEMANTIC SCORING (Sentence-BERT):")
try:
    from sentence_transformers import SentenceTransformer, util as st_util
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Test semantic similarity
    response = 'Job 4001 is currently running on gpu partition with user bob'
    fact1 = '4001'  # Exact match
    fact2 = 'running jobs on GPU'  # Semantic
    
    resp_emb = model.encode(response, convert_to_tensor=True)
    f1_emb = model.encode(fact1, convert_to_tensor=True)
    f2_emb = model.encode(fact2, convert_to_tensor=True)
    
    sim1 = st_util.cos_sim(f1_emb, resp_emb).item()
    sim2 = st_util.cos_sim(f2_emb, resp_emb).item()
    
    print(f'   ✓ Semantic model loaded: all-MiniLM-L6-v2')
    print(f'   Test 1: "4001" vs response = {sim1:.3f}')
    print(f'   Test 2: "running jobs on GPU" vs response = {sim2:.3f}')
    print(f'   → Semantic matching is ACTIVE')
except Exception as e:
    print(f'   ✗ Semantic model error: {e}')
    print(f'   → Falling back to substring matching')

# Check LLM-as-judge
print("\n2. LLM-AS-JUDGE (Ollama):")
try:
    from openai import OpenAI
    client = OpenAI(base_url='http://localhost:11434/v1', api_key='ollama')
    
    resp = client.chat.completions.create(
        model='qwen3-coder:latest',
        messages=[{'role': 'user', 'content': 'Rate this response quality from 0.0 to 1.0. Just output a single number, nothing else: "Hello, I can help you with Slurm jobs."'}],
        max_tokens=10,
        temperature=0
    )
    score = resp.choices[0].message.content.strip()
    print(f'   ✓ Ollama connection successful')
    print(f'   Model: qwen3-coder:latest')
    print(f'   Sample judge response: "{score}"')
    print(f'   → LLM-as-judge is ACTIVE')
except Exception as e:
    print(f'   ✗ LLM-as-judge error: {e}')
    print(f'   → Falling back to heuristic scoring')

print("\n" + "=" * 50)
print("SUMMARY")
print("=" * 50)
