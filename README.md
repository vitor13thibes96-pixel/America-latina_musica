# América Latina Música — automação de imagens

Este pacote pesquisa imagens para os artistas que já aparecem em cards HTML, baixa imagens com metadados de licença e atualiza apenas o `src` dos elementos `<img>`. Os textos e a estrutura dos cards são preservados.

## Como funciona

- Percorre arquivos `.html` do projeto.
- Por padrão, processa imagens com `src` ausente, vazio, apontando para arquivo inexistente ou placeholder. Para substituir imagens existentes, habilite `REPLACE_EXISTING` no workflow.
- Usa o texto de `alt` como nome prioritário do artista; quando o `alt` é genérico, tenta obter o nome do card próximo.
- Pesquisa no Wikimedia Commons. A integração Flickr é opcional e só é usada se `FLICKR_API_KEY` estiver configurada.
- Salva arquivos em `img/` e registra fonte, página, autor e licença em `img/attributions.csv`.
- Imagens de correspondência incerta são registradas em `img/review-needed.csv` e não são inseridas automaticamente.

**Importante:** nenhum sistema de busca consegue garantir que toda fotografia representa a pessoa certa. Revise `review-needed.csv` e o relatório de atribuições antes de publicar. Respeite os termos e as licenças indicados por cada fonte.

## Configuração no GitHub (online)

1. Envie o projeto do site para um repositório GitHub.
2. Copie `scripts/auto_images.py`, `requirements.txt` e `.github/workflows/auto-images.yml` para a raiz desse repositório.
3. Abra **Settings → Actions → General** e permita workflows, se ainda não estiverem habilitados.
4. Em **Settings → Secrets and variables → Actions**, adicione `FLICKR_API_KEY` se você tiver uma chave da API Flickr. É opcional.
5. Em **Settings → Actions → General → Workflow permissions**, habilite permissão de leitura e escrita para workflows que precisem enviar alterações. O workflow também declara `contents: write`.
6. Abra **Actions → Automatizar imagens dos artistas → Run workflow**. A primeira execução deve ser revisada.
7. Após a execução, confira o commit gerado, `img/attributions.csv` e `img/review-needed.csv`.

O workflow roda apenas quando acionado manualmente. Não faz varredura periódica nem altera o site publicado por conta própria; ele envia um commit para o repositório. Se o site usa GitHub Pages a partir desse branch, a publicação costuma ocorrer conforme as configurações do Pages.

## Execução local (opcional)

```bash
python -m pip install -r requirements.txt
python scripts/auto_images.py --root .
```

Para substituir também imagens existentes:

```bash
python scripts/auto_images.py --root . --replace-existing
```

## Limites e segurança

- O script nunca apaga imagens antigas; substitui apenas o caminho no HTML quando encontra uma candidata utilizável.
- As imagens são baixadas com limite de tamanho e validação do tipo MIME.
- Não baixa resultados de sites arbitrários de busca; usa APIs públicas documentadas.
- `FLICKR_API_KEY` é opcional. Não coloque chaves diretamente no código ou em arquivos commitados.
- A busca prioriza nomes explícitos no `alt`. Cards sem nome acessível podem ser ignorados e listados no log.
