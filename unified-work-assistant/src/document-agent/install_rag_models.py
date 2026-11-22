"""Explicit install-time download only. Runtime is local_files_only and offline."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download, hf_hub_download

E5='614241f622f53c4eeff9890bdc4f31cfecc418b3'
QWEN='cdbee75f17c01a7cc42f958dc650907174af0554'
root=Path('/models')
snapshot_download('intfloat/multilingual-e5-small',revision=E5,local_dir=str(root/'e5'),
    allow_patterns=['*.json','*.safetensors','*.txt','sentencepiece.bpe.model','1_Pooling/*','README.md'])
hf_hub_download('Qwen/Qwen3-4B-Instruct-2507','tokenizer.json',revision=QWEN,local_dir=str(root/'qwen'))
(root/'e5'/'PROFILE').write_text('e5-small-'+E5+'-chunks-v1')
(root/'manifest.json').write_text(json.dumps({'embedding_model':'intfloat/multilingual-e5-small','embedding_revision':E5,
    'dimension':384,'license':'MIT','qwen_tokenizer_revision':QWEN,'device':'cpu'},indent=2))
print('Installed pinned E5 model and Qwen tokenizer. Runtime downloads disabled.')
