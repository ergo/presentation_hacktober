import string
import pathlib
import markdown
import time
import logging
import os

from shutil import copy2, copystat, Error

from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler

logging.basicConfig(level=logging.WARNING)

log = logging.getLogger(__name__)


class Config:
    def __init__(self, template_pkg, index_path):
        self.template_pkg = template_pkg
        self.template_path = pathlib.Path(template_pkg).absolute()
        self.index_path = index_path
        self.assets_path = index_path.parent / "assets"
        self.output_path = pathlib.Path("docs").absolute()


class Slide:
    def __init__(self, markdown_text, index):
        self.reveal_md = True
        md = markdown.Markdown(
            extensions=[
                "markdown.extensions.abbr",
                "markdown.extensions.attr_list",
                "markdown.extensions.def_list",
                "markdown.extensions.footnotes",
                "markdown.extensions.tables",
                "markdown.extensions.admonition",
                "markdown.extensions.codehilite",
                "markdown.extensions.meta",
                "markdown.extensions.attr_list",
            ]
        )
        html = md.convert(markdown_text.strip())
        self.meta = md.Meta
        self.markdown = markdown_text
        self.html = html
        self.index = index

    def render(self):
        class_ = f"slide slide-{self.index}"
        meta_pairs = []
        for k, v in self.meta.items():
            if k.startswith("data-"):
                meta_pairs.append(f'{k}="{v[0]}"')
        meta = " ".join(meta_pairs)
        if self.reveal_md:
            return f"""
            <section data-markdown>
            <textarea data-template>
            {self.markdown}
            </textarea>
            </section>"""
        return f'<section class="{class_}" {meta}>{self.html}</section>'

    @property
    def rendered(self):
        return self.render()


# copied from stdlib and patched to not error out on existing directories
def copytree(
    src,
    dst,
    symlinks=False,
    ignore=None,
    copy_function=copy2,
    ignore_dangling_symlinks=False,
):

    names = os.listdir(src)
    if ignore is not None:
        ignored_names = ignore(src, names)
    else:
        ignored_names = set()
    # do not fail on existing dirs
    os.makedirs(dst, exist_ok=True)
    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if os.path.islink(srcname):
                linkto = os.readlink(srcname)
                if symlinks:
                    # We can't just leave it to `copy_function` because legacy
                    # code with a custom `copy_function` may rely on copytree
                    # doing the right thing.
                    os.symlink(linkto, dstname)
                    copystat(srcname, dstname, follow_symlinks=not symlinks)
                else:
                    # ignore dangling symlink if the flag is on
                    if not os.path.exists(linkto) and ignore_dangling_symlinks:
                        continue
                    # otherwise let the copy occurs. copy2 will raise an error
                    if os.path.isdir(srcname):
                        copytree(srcname, dstname, symlinks, ignore, copy_function)
                    else:
                        copy_function(srcname, dstname)
            elif os.path.isdir(srcname):
                copytree(srcname, dstname, symlinks, ignore, copy_function)
            else:
                # Will raise a SpecialFileError for unsupported file types
                copy_function(srcname, dstname)
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except Error as err:
            errors.extend(err.args[0])
        except OSError as why:
            errors.append((srcname, dstname, str(why)))
    try:
        copystat(src, dst)
    except OSError as why:
        # Copying file access times may fail on Windows
        if getattr(why, "winerror", None) is None:
            errors.append((src, dst, str(why)))
    if errors:
        raise Error(errors)
    return dst


def grab_slides(config):
    presentation_chunks = config.index_path.read_text("utf8").split("---------")
    return [
        Slide(markdown_text=slide_md, index=ix)
        for ix, slide_md in enumerate(presentation_chunks, 1)
    ]


def generate_presentation(config):
    print("Generating presentation")
    template = string.Template(
        (config.template_path / "template.html").read_text("utf8")
    )
    slides = grab_slides(config)
    sections = [s.rendered for s in slides]
    rendered_template = template.safe_substitute(slides="\n".join(sections))

    def copy_ignore(dir_, filelist):
        if config.template_path == pathlib.Path(dir_):
            return ["template.html"]
        return []

    config.output_path.mkdir(exist_ok=True)
    copytree(config.template_path, config.output_path, ignore=copy_ignore)
    print("Templating...")
    (config.output_path / "index.html").write_text(rendered_template, "utf8")
    if config.assets_path.exists():
        print(f"Copying {config.assets_path} to output dir")
        copytree(config.assets_path, config.output_path / "assets")
    else:
        print(f"Assets dir not found in {config.assets_path}")

    print("...Done...")


class PotatoStampHandler(LoggingEventHandler):
    def __init__(self, config):
        self.config = config

    def on_modified(self, event):
        super().on_modified(event)
        what = "directory" if event.is_directory else "file"

        index_changed = (
            not event.is_directory
            and self.config.index_path == pathlib.Path(event.src_path)
        )
        assets_changed = event.is_directory and self.config.assets_path == pathlib.Path(
            event.src_path
        )
        if index_changed or assets_changed:
            generate_presentation(self.config)


if __name__ == "__main__":
    index_path = pathlib.Path("open_source/index.md").absolute()
    config = Config(template_pkg="revealjs_template", index_path=index_path)
    generate_presentation(config)
    event_handler = PotatoStampHandler(config)
    observer = Observer()
    observer.schedule(event_handler, str(config.index_path.parent), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
