import os
from functools import lru_cache
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_FOLDER = os.path.join(BASE_DIR, "context")
FAISS_PATH = os.path.join(BASE_DIR, "faiss_db")

def _is_git_lfs_pointer(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(64).startswith(b"version https://git-lfs.github.com/spec")
    except FileNotFoundError:
        return False


def _has_usable_faiss_index() -> bool:
    index_files = [
        os.path.join(FAISS_PATH, "index.faiss"),
        os.path.join(FAISS_PATH, "index.pkl"),
    ]
    return all(os.path.exists(path) and not _is_git_lfs_pointer(path) for path in index_files)


@lru_cache(maxsize=1)
def build_or_load_faiss():
    """Build the retriever once and reuse it for subsequent chat requests."""
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    if _has_usable_faiss_index():
        print("📂 Loading existing FAISS index...")
        vectorstore = FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)
    else:
        if any(
            _is_git_lfs_pointer(os.path.join(FAISS_PATH, name))
            for name in ("index.faiss", "index.pkl")
        ):
            raise RuntimeError(
                "FAISS index files are Git LFS pointers. Run `git lfs pull` "
                "or rebuild the vector database from PDFs in context/."
            )
        if not os.path.isdir(PDF_FOLDER):
            raise RuntimeError("Missing context/ folder for building the FAISS vector database.")

        print("⚡ Building FAISS index from PDFs...")
        pdf_files = [os.path.join(PDF_FOLDER,f) for f in os.listdir(PDF_FOLDER) if f.endswith(".pdf")]
        if not pdf_files:
            raise RuntimeError("No PDF files found in context/ for building the FAISS vector database.")

        docs = []
        for pdf in pdf_files:
            loader = PyPDFLoader(pdf)
            docs.extend(loader.load())

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap = 150)
        splits = text_splitter.split_documents(docs)

        vectorstore = FAISS.from_documents(splits, embedding=embeddings)

        os.makedirs(FAISS_PATH,exist_ok = True)
        vectorstore.save_local(FAISS_PATH)
        print(f"FAISS index saved to {FAISS_PATH}")

    retriever = vectorstore.as_retriever(search_kwargs={"k":5})
    return retriever

if __name__ == "__main__":
    retriever = build_or_load_faiss()
