'''
Bluetooth LE CTP500 thermal printer client by Mel at ThirtyThreeDown Studio
See https://thirtythreedown.com/2025/11/02/pc-app-for-walmart-thermal-printer/ for process and details!
Shout out to Bitflip, Tsathoggualware, Reid and all the mad lasses and lads whose research made this possible!

'''

#System imports
import socket
import sys
import os
import glob
from time import sleep, monotonic
import struct

#Tkinter imports
import tkinter as tk
from tkinter import Frame, Label, Button, Text, Radiobutton, messagebox
from tkinter.messagebox import showinfo
from tkinter import filedialog as fd
from tkinter import scrolledtext
from tkinter import ttk

#PILLOW imports
import PIL.Image
import PIL.ImageTk
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageChops
import PIL.ImageOps

#COMMUNICATION LOGIC STARTS HERE
mac_address = "00:00:00:00:00:00" #Put in your printer's Bluetooth device address here - you can find it in the app
if sys.platform == "darwin": #macOS Python has no AF_BLUETOOTH, so we open the RFCOMM channel through Apple's IOBluetooth instead
    from Foundation import NSObject, NSRunLoop, NSDate #pip install pyobjc-framework-IOBluetooth
    from IOBluetooth import IOBluetoothDevice

    class CTP500RFCOMMDelegate(NSObject): #macOS hands us the printer's replies through this callback
        def rfcommChannelData_data_length_(self, channel, data, length):
            self.received += bytes(data)

    class MacRFCOMMSocket: #Same send/recv/close as a socket, so the rest of the app doesn't care which one it has
        def __init__(self, address):
            self.delegate = CTP500RFCOMMDelegate.alloc().init()
            self.delegate.received = bytearray()
            device = IOBluetoothDevice.deviceWithAddressString_(address.replace(":", "-"))
            if device is None:
                raise OSError(f"Bad Bluetooth address: {address}")
            result, self.channel = device.openRFCOMMChannelSync_withChannelID_delegate_(None, 1, self.delegate) #Channel 1, same as the Linux/Windows socket
            if result != 0:
                raise OSError(f"Could not open RFCOMM channel 1 (IOReturn {result:#x}) - is the printer on and paired?")

        def send(self, data):
            mtu = self.channel.getMTU() #Writes bigger than the channel MTU get rejected, so we chunk them
            for i in range(0, len(data), mtu):
                chunk = data[i:i + mtu]
                result = self.channel.writeSync_length_(chunk, len(chunk))
                if result != 0:
                    raise OSError(f"Bluetooth write failed (IOReturn {result:#x})")
            return len(data)

        def recv(self, size):
            deadline = monotonic() + 5 #Waiting up to 5s so a silent printer can't freeze the app
            while not self.delegate.received and monotonic() < deadline:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1)) #Letting macOS deliver incoming data
            if not self.delegate.received:
                raise TimeoutError("Printer did not respond")
            data = bytes(self.delegate.received[:size])
            del self.delegate.received[:size]
            return data

        def shutdown(self, how): #Nothing to shut down separately, close() handles it
            pass

        def close(self):
            self.channel.closeChannel()
            self.channel.getDevice().closeConnection()

def open_connection(address): #Opens the printer's RFCOMM channel 1, returning something with send/recv/shutdown/close
    if sys.platform == "darwin":
        return MacRFCOMMSocket(address)
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) #Setting up the Bluetooth socket with RFCOMM protocol
    try:
        sock.connect((address, 1)) #Connection instruction with address and port to use
    except OSError:
        sock.close()
        raise
    return sock

class PrinterConnect: #Starting a PrinterConnect class to keep track of connection status
    def __init__(self):
        self.socket = None #Starting a disconnect socket
        self.connected = False #Setting socket status to False/disconnected

    def connect(self, mac_address): #Setting up a connection function
        if self.connected: #Checking to see if the printer is already connected
            print("Already connected") #Warning user
            return True #Switching PrinterConnect socket status

        try: #Starting all the things to do to establish a connection
            self.socket = open_connection(mac_address)

            print("Getting printer status")
            status = self.get_printer_status() #Calling the get_printer_status() function and storing it in status variable
            print(f'Printer status: {status}') #Displaying status variable

            self.connected = True #Switching connection status for tracking
            print("Connection established")
            return True #Returning status

        except Exception as e: #Exception handling in case something goes wrong
            print(f'Connection error: {e}')
            if self.socket: #If the socket connection is present:
                self.socket.close() #Closing the connection
                self.socket = None #Clearing the socket references
            raise #Letting the GUI (popup) or CLI (stderr) report it

    def disconnect(self): #Function to disconnect the socket
        if not self.connected or not self.socket: #First a status check to see if already disconnected
            print("Not connected") #Communication to user
            return #Calling it a day

        try:
            print("Disconnecting printer")
            print("Releasing Bluetooth comm resources")
            self.socket.shutdown(socket.SHUT_RDWR) #Releasing comms resources

            print("Cutting connection")
            self.socket.close()

            print("Clearing socket references")
            self.socket = None #Clearing socket refs
            self.connected = False #Switching connection status tracking
            print("Disconnected")

        except Exception as e:
            print(f'Disconnection error: {e}') #Exception warning
            if self.socket: #In case of connection shutdown failure, we close anyway
                self.socket.close() #Closing socket
                self.socket = None #Clearing the socket
            self.connected = False #Setting socket status to false


    def get_printer_status(self):
        if not self.socket:
            raise Exception("Not connected")
        self.socket.send(b"\x1e\x47\x03") #Hex code for status request
        return self.socket.recv(38) #Returning status request content


printer = PrinterConnect() #Creating a printer connection instance here. Having it *outside* of a function lets us run and monitor connection across global scope
printerWidth = 384  # For CPT500
#PRINTER COMMUNICATION LOGIC AND SETUP ENDS HERE

#IMAGE DATA STORAGE STARTS HERE
current_image = None #Variable to store full resolution image
image_thumbnail = None #Variable to store image thumbnail
image_preview = None #Variable to store image preview for PhotoImage and canvas
#IMAGE DATA STORAGE ENDS HERE

#TEXT FILE MANAGEMENT STARTS HERE
def selectTextFile():
    textFilePath = fd.askopenfilename(
        title = "Open a text file",
        initialdir = "/"
    )

    showinfo(
        title="Selected file: ",
        message = textFilePath
    )

#SOMETHING WEIRD IS HAPPENING HERE, FAILURE TO CAPTURE INPUT FIELD
    if textFilePath:
        try:
            with open(textFilePath, 'r', encoding='utf-8') as textFile: #Using the file path we got from the user to read the file
                textFileContent=textFile.read()
                textInputField.delete('1.0', tk.END) #Clearing previously typed content
                textInputField.insert(tk.END, textFileContent) #Inserting the text file content

            #Insert some sort of status bar system here? Success messages and exception messages
            #Status Bar stuff
        except Exception as e:
            print("Woops, something went wrong.")
#TEXT FILE MANAGEMENT ENDS HERE

#TEXT AND IMAGE INPUT RENDERING AND PRINTING STARTS HERE
def create_text(text, font_name="Lucon.ttf", font_size=28, align="left"):
    #Tweak to be able to change font w/ system fonts
    img = PIL.Image.new('RGB', (printerWidth, 5000), color=(255, 255, 255)) #Defines an RGB image, width is printer width, height is 5000px, color is white
    try:
        font = PIL.ImageFont.truetype(font_name, font_size) #Loads up font_name as the default font, at font_size default size
    except OSError: #Lucon.ttf (Lucida Console) only ships with Windows, so we fall back to Pillow's built-in font elsewhere
        font = PIL.ImageFont.load_default(font_size)

    d = PIL.ImageDraw.Draw(img) #Creates the d image object using the parameters above
    lines = [] #Creates an empty Python list to store lines of text
    for line in text.splitlines(): #Combing through text looking for line splits
        lines.append(get_wrapped_text(line, font, printerWidth)) #Creating a new lines list item at each line split
    lines = "\n".join(lines) #Recombining all the lines list items with a "\n" line jump instruction at each line break
    x, anchor = {"left": (0, "la"), "center": (printerWidth // 2, "ma"), "right": (printerWidth, "ra")}[align] #Where the lines line up on the paper
    d.text((x, 0), lines, fill=(0, 0, 0), font=font, anchor=anchor, align=align) #Drawing our text onto our d object
    return trimImage(img) #Trimming down the unused height of the d object using the trimImage() function above

def get_wrapped_text(text: str, font: PIL.ImageFont.ImageFont, line_length: int): #Function to wrap the text to printer paper width
    lines = [''] #Empty list to store the lines
    for word in text.split(): #Iterating through the split words composing a sentence
        line = f'{lines[-1]} {word}'.strip() #Composing a "candidate line" out of words, one word at a time
        if font.getlength(line) <= line_length: #If the pixel length of the line is shorter than the printer width...
            lines[-1] = line #...We keep doing that!
        else:
            lines.append(word) #...Otherwise we create a new line in the list of lines, and continue from the next word on.
    return '\n'.join(lines) #Done processing the text, returning the lines dictionary as a text with line returns!

def can_print_text(font_path): #Symbol fonts (Braille, Wingdings, emoji...) and other-script fonts have no Latin letters and print boxes, so we hide them
    try:
        font = PIL.ImageFont.truetype(font_path, 20)
    except OSError:
        return False

    def draw(character):
        im = PIL.Image.new("L", (48, 48))
        PIL.ImageDraw.Draw(im).text((8, 8), character, font=font, fill=255)
        return im.tobytes()

    box = draw("\U0010FFFD") #No font has this character, so this is what the font's "missing" box looks like
    return all(draw(character) != box for character in "Aa0.,!?&")

#Font files in the usual system font folders, shared by the GUI picker and the CLI
font_dirs = {"darwin": ["/System/Library/Fonts", "/Library/Fonts", "~/Library/Fonts"],
             "win32": [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")]}.get(sys.platform, ["/usr/share/fonts", "~/.local/share/fonts", "~/.fonts"])
system_fonts = {os.path.splitext(os.path.basename(path))[0]: path #Font name -> font file path
                for folder in font_dirs
                for path in glob.glob(os.path.join(os.path.expanduser(folder), "**", "*.[ot]t[cf]"), recursive=True)} #.ttf .ttc .otf .otc
default_font = next((name for name in sorted(system_fonts) if name.lower() in ("lucon", "menlo", "dejavusansmono")), "") #A monospace font like the original Lucida Console
font_size_options = {"small": 20, "medium": 28, "large": 40} #Font sizes in pixels, the paper is 384px wide

#Creating our list of justification options
justification_options = ["left",
                 "center",
                 "right"]

def print_from_entry():
    txt = textInputField.get("1.0", tk.END).strip() # Grab the text from the scrolled‑text widget
    if not txt:
        messagebox.showwarning("No text", "Please type or load some text.")
        return

    img = create_text(txt, system_fonts.get(fontPicker.get(), "Lucon.ttf"), radioFontSize_status.get(), justification_options[radioJustification_status.get()]) #Turning the text to image with the picked font, size and alignment
    show_print_preview(img)

def print_from_image():
    """Preview the currently loaded image, then send it to the printer."""
    if not current_image:
        messagebox.showwarning("No image", "Please load an image first.")
        return
    show_print_preview(current_image)

def show_print_preview(img): #Showing exactly what will come out of the printer before sending it
    preview = prepare_image(img)
    window = tk.Toplevel(root)
    window.title("Print preview")

    buttons = Frame(window) #Packing the buttons first so a tall preview can't push them off screen
    buttons.pack(side="bottom", fill="x")

    canvas = tk.Canvas(window, width=preview.width, height=min(preview.height, 500), bg="white", highlightthickness=0)
    scrollbar = tk.Scrollbar(window, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set, scrollregion=(0, 0, preview.width, preview.height))
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")) #Tk canvases don't scroll with the wheel/trackpad on their own

    window.photo = PIL.ImageTk.PhotoImage(preview) #Keeping a reference on the window, otherwise Tk drops the image
    canvas.create_image(0, 0, anchor="nw", image=window.photo)

    def print_and_close():
        if send_to_printer(img):
            window.destroy()

    Button(buttons, text="Print", padx=10, pady=10, command=print_and_close).pack(side="left", expand=True, fill="x")
    Button(buttons, text="Cancel", padx=10, pady=10, command=window.destroy).pack(side="left", expand=True, fill="x")

def print_job(img, feed=True): #Print sequence shared by the GUI and CLI, raises if anything goes wrong
    print("Initializing printer")
    initializePrinter(printer.socket)
    sleep(0.5)

    print("Starting print sequence")
    sendStartPrintSequence(printer.socket)
    sleep(0.5)

    print("Printing image")
    printImage(printer.socket, img)

    if feed: #The end sequence feeds paper out; skipping it lets the next printout continue right below this one
        print("Sending end sequence")
        sleep(0.5)
        sendEndPrintSequence(printer.socket)

def send_to_printer(img): #GUI printing: problems show up as popups
    if not (printer.connected and printer.socket):
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")
        return False

    try:
        print_job(img)
        return True
    except Exception as e:
        messagebox.showerror("Printing error", str(e))
        return False

def connect_from_gui(): #Connect button: problems show up as popups
    try:
        printer.connect(mac_address)
    except Exception as e:
        messagebox.showerror("Connection Error", f'Failed to connect with printer: {e}')


#IMAGE FILE SECTION STARTS HERE
def selectImageFile():
    global current_image, image_thumbnail, image_preview
    imageFilepath = fd.askopenfilename(
        title = "Open an image file",
        initialdir = "/",
        filetypes = (('PNG files', '*.png'), ('JPG files', '*.jpg'), ('jpeg files', '*.jpeg'), ('BMP files', '*.bmp'), ('SVG files', '*.svg'), ('all files', '*.*'))
        )

    showinfo(
        title="Selected file: ",
        message = imageFilepath
    )

#SOMETHING WEIRD IS HAPPENING HERE, FAILURE TO CAPTURE INPUT FIELD
    if imageFilepath:
        try:
            print("Opening image file")
            current_image = PIL.Image.open(imageFilepath, 'r') #Storing the image contents into imageFile variable
            print(current_image)
            image_thumbnail = current_image.copy() #Copying current_image into image_thumbnail
            print(image_thumbnail)
            image_thumbnail.thumbnail((300, 100)) #Resizing image_thumbail to canvas size (might not work)

            print("Generating preview")
            imageCanvas_width = imageCanvas.winfo_width() #Storing the width of the preview canvas
            imageCanvas_height = imageCanvas.winfo_height() #Storing the height of the preview canvas
            imageCanvas_x_center = imageCanvas_width//2 #Calculating x center of the preview canvas
            imageCanvas_y_center = imageCanvas_height//2 #Calculating y center of the preview canvas

            image_preview = PIL.ImageTk.PhotoImage(image_thumbnail) #Storing the thumbnail as a displayable object into image_preview
            imageCanvas.delete('all')  #Clearing any  previous image from the canvas display
            imageCanvas.create_image(imageCanvas_x_center, imageCanvas_y_center, anchor = "center", image=image_preview)  # Loading up the thumbnail into the center of the preview canvas

        except Exception as e:
            print("Woops, something went wrong.")
            print({e})
#IMAGE FILE SECTION ENDS HERE

def prepare_image(im): #Scaling/padding to printer width and converting to 1-bit black and white, i.e. exactly what prints
    if im.width > printerWidth:
        # Image is wider than printer resolution; scale it down proportionately
        height = int(im.height * (printerWidth / im.width))
        im = im.resize((printerWidth, height))

    if im.width < printerWidth:
        # Image is narrower than printer resolution; pad it out with white pixels
        padded_image = PIL.Image.new("1", (printerWidth, im.height), 1)
        padded_image.paste(im)
        im = padded_image

    #Add a function for text rotation
    # im = im.rotate(180)  # Print it so it looks right when spewing out of the mouth

    # If image is not 1-bit, convert it
    if im.mode != '1':
        im = im.convert('1')

    # If image width is not a multiple of 8 pixels, fix that
    if im.size[0] % 8:
        im2 = PIL.Image.new('1', (im.size[0] + 8 - im.size[0] % 8, im.size[1]), 'white')
        im2.paste(im, (0, 0))
        im = im2
    return im

def printImage(socket, im):
    im = prepare_image(im)

    # Invert image, via greyscale for compatibility
    im = PIL.ImageOps.invert(im.convert('L'))
    # ... and now convert back to single bit
    im = im.convert('1')

    buf = b''.join((bytearray(b'\x1d\x76\x30\x00'),
                    struct.pack('2B', int(im.size[0] / 8 % 256),
                                int(im.size[0] / 8 / 256)),
                    struct.pack('2B', int(im.size[1] % 256),
                                int(im.size[1] / 256)),
                    im.tobytes()))

    socket.send(buf)

def trimImage(im):
    bg = PIL.Image.new(im.mode, im.size, (255, 255, 255))
    diff = PIL.ImageChops.difference(im, bg)
    diff = PIL.ImageChops.add(diff, diff, 2.0)
    bbox = diff.getbbox()
    if bbox:
        return im.crop((0, bbox[1], im.width, bbox[3] + 10))  # Trimming height only, keeping full width so center/right alignment survives. Don't cut off the end of the image

def initializePrinter(soc):
    soc.send(b"\x1b\x40")

def sendStartPrintSequence(soc):
    #Check against hex dump
    soc.send(b"\x1d\x49\xf0\x19")

def sendEndPrintSequence(soc):
    #Check against hex dump. Missings \x9a?
    soc.send(b"\x0a\x0a\x0a\x9a")

#TEXT AND IMAGE INPUT RENDERING AND PRINTING ENDS HERE

#COMMAND LINE MODE STARTS HERE
def run_cli():
    import argparse
    parser = argparse.ArgumentParser(
        description="Print to a CTP500 thermal printer. Run with no arguments for the GUI.",
        epilog='examples:\n'
               '  %(prog)s "Hello world"\n'
               '  echo "build finished" | %(prog)s -\n'
               '  tail -f /var/log/apache2/error.log | %(prog)s --follow --no-feed --size small    # ticker tape\n'
               '  %(prog)s --image todo.png',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="*", help="text to print; leave it out or use - to read stdin")
    parser.add_argument("-f", "--follow", action="store_true", help="ticker tape: stay connected and print each stdin line as it arrives")
    parser.add_argument("-n", "--no-feed", action="store_true", help="don't feed paper after each printout, so the next one prints right below it (--follow still feeds once when it stops)")
    parser.add_argument("-i", "--image", help="image file to print instead of text")
    parser.add_argument("--font", default=default_font, help=f"font name from --list-fonts, or a font file path (default: {default_font})")
    parser.add_argument("--size", choices=font_size_options, default="medium", help="text size (default: medium)")
    parser.add_argument("--align", choices=justification_options, default="left", help="text alignment (default: left)")
    parser.add_argument("--address", default=mac_address, help=f"printer Bluetooth address (default: {mac_address})")
    parser.add_argument("--list-fonts", action="store_true", help="list the fonts that can print text, then exit")
    args = parser.parse_args()

    if args.list_fonts:
        print("\n".join(sorted((name for name, path in system_fonts.items() if can_print_text(path)), key=str.lower)))
        return 0

    font = system_fonts.get(args.font, args.font) #Accepting a font name or a path to a font file
    if font and not os.path.isfile(font): #No font at all is fine, create_text falls back to Pillow's built-in one
        parser.error(f"unknown font {args.font!r}, see --list-fonts")

    def render(text):
        return create_text(text, font, font_size_options[args.size], args.align)

    if args.follow:
        jobs = (render(line) for line in sys.stdin if line.strip()) #Rendering each line as it arrives
    elif args.image:
        try:
            jobs = [PIL.Image.open(args.image)]
        except OSError as e: #Missing file or not an image
            parser.error(f"can't open image: {e}")
    else:
        text = sys.stdin.read() if args.text in ([], ["-"]) else " ".join(args.text)
        if not text.strip():
            parser.error("nothing to print")
        jobs = [render(text)]

    sys.stdout = sys.stderr #Status chatter goes to stderr so scripts calling us keep a clean stdout
    failed = False
    try:
        for img in jobs:
            for attempt in range(2): #Retrying once on a fresh connection, in case the printer slept or dropped
                try:
                    if not printer.connected:
                        printer.connect(args.address) #Connecting on the first job, so a --follow ticker can start before the printer is on
                    print_job(img, feed=not args.no_feed)
                    break
                except Exception as e:
                    print(f"Printing failed: {e}")
                    printer.disconnect()
            else:
                failed = True #Both tries failed; a --follow ticker logs it and keeps going
    except KeyboardInterrupt: #Ctrl-C stops a --follow ticker cleanly
        pass
    finally:
        if args.follow and args.no_feed and printer.connected: #Feeding once at the end so the last lines clear the tear bar
            try:
                sendEndPrintSequence(printer.socket)
            except Exception as e:
                print(f"Final paper feed failed: {e}")
        printer.disconnect()
    return 1 if failed else 0

#COMMAND LINE MODE ENDS HERE

#GUI SETUP STARTS HERE
def run_gui():
    global root, textInputField, imageCanvas, fontPicker, radioJustification_status, radioFontSize_status #Widgets the callbacks above read

    root = tk.Tk()
    frame = Frame(root)
    frame.pack()

    #Setting up window properties
    root.title("CTP500 Printer Control")
    root.configure() #Sets background color of the window. We will tweak this later to be able to select from printer colors and patterns
    root.minsize(520, 640) #Sets min size of the window
    root.geometry("520x640") #Changes original rendering position of the window

    #BLUETOOTH TOOLS SECTION STARTS HERE
    bluetoothFrame = Frame(root,
                           borderwidth=1,
                           padx=5,
                           pady=5)

    bluetoothLabel = Label(bluetoothFrame, text = "Bluetooth tools")
    bluetoothLabel.pack(fill="x")

    #Setting up connection button
    connectButton = tk.Button(
        bluetoothFrame,
        text = "Connect",
        command=connect_from_gui,
        padx = 15,
        pady = 15
    ).pack(
        side="left",
        expand=1
    )

    #Setting up disconnection button
    disconnectButton = tk.Button(
        bluetoothFrame,
        text = "Disconnect",
        command=lambda: printer.disconnect(),
        padx = 15,
        pady = 15
    ).pack(
        side="left",
        expand=1
    )

    bluetoothFrame.pack() #Rendering bluetoothFrame
    #BLUETOOTH TOOLS SECTION ENDS HERE

    #TEXT TOOLS SECTION STARTS HERE
    textFrame = Frame(root)
    radioButtonsFrame = Frame(textFrame)

    radioJustification_status = tk.IntVar() #Creating a watch state for the radio buttons for justification

    textLabel = Label(textFrame, text="Text tools")
    textLabel.pack(fill="x") #Text label for the text input section

    for index in range(len(justification_options)): #Iterating through the list of justification options
        Radiobutton(radioButtonsFrame,
                    text=justification_options[index],
                    variable=radioJustification_status,
                    value=index, padx=5).pack(side="left", expand=True) #Creating a button for each justification option

    radioButtonsFrame.pack(fill="x", pady=(0, 5)) #Rendering the frame for the Justification radio buttons
    #radioButtonsFrame.pack(fill="x", expand=1) #Rendering the frame for the Justification radio buttons

    #Font picker: only fonts that can actually print letters
    fontFrame = Frame(textFrame)
    Label(fontFrame, text="Font").pack(side="left")
    fontPicker = ttk.Combobox(fontFrame, values=sorted((name for name, path in system_fonts.items() if can_print_text(path)), key=str.lower), state="readonly")
    fontPicker.set(default_font)
    fontPicker.pack(side="left", fill="x", expand=True, padx=5)

    radioFontSize_status = tk.IntVar(value=font_size_options["medium"]) #Creating a watch state for the font size radio buttons
    for name, size in font_size_options.items(): #Creating a button for each font size
        Radiobutton(fontFrame, text=name, variable=radioFontSize_status, value=size, padx=5).pack(side="left")
    fontFrame.pack(fill="x", pady=(0, 5)) #Rendering the font picker row

    textInputField = scrolledtext.ScrolledText(textFrame, height=5, width=40) #Creating a text input widget to input text
    textInputField.pack(fill="both") #Rendering the text input widget
    textButton = Button(textFrame,
                        text="Select a text file",
                        padx=10, pady=15,
                        command=selectTextFile)
    textButton.pack(expand=1, fill="x")
    textFrame.pack(fill="both") #Rendering the text input area frame

    #Creating a frame for the Print Text button
    # printTextFrame = Frame(textFrame)
    printTextButton = Button(textFrame,
                             text="Print your text!",
                             padx=10, pady=15,
                             command=print_from_entry)
    printTextButton.pack(fill="x", pady=(5, 0))
    # printTextFrame.pack(side="bottom", expand=1, fill="x")
    #TEXT TOOLS SECTION ENDS HERE

    #IMAGE TOOLS SECTION STARTS HERE
    #Creating a frame for the image selection area
    imageFrame = Frame(root)
    imageLabel = Label(imageFrame, text="Image tools").pack(fill="x", pady=(0,5))

    #Creating a canvas to display the image selection
    imageCanvas = tk.Canvas(imageFrame,
                            width=300,
                            height=100,
                            bg = "white")
    imageCanvas.pack(pady=(0,5)) #Rendering the image selection canvas

    imageDisplay = Frame(imageFrame).pack(fill="both")  #Rendering the selected image to the image selection area

    imageButton = Button(imageFrame,
                         text="Select an image file",
                         padx=10, pady=15,
                         command=selectImageFile)
    imageButton.pack(fill="x")
    #Displaying selected picture

    #Creating a frame for the Print Image button
    #printImageFrame = Frame(imageFrame)
    printImageButton = Button(imageFrame,
                              text="Print your image!",
                              padx=10, pady=15,
                              command=print_from_image)
    printImageButton.pack(fill="x", pady=(5, 0))
    imageFrame.pack(fill="both", expand=True, padx=10, pady=5)
    #IMAGE TOOLS SECTION ENDS HERE

    def on_closing(): #Cleanup operations when closing the window
        printer.disconnect() #Disconnecting the printer
        root.destroy() #Flushing the UI

    root.protocol("WM_DELETE_WINDOW", on_closing) #Final window cleanup on app closing

    root.mainloop() #If your mainloop() runs before your options, then nothing will show up. Keep that in mind!

if __name__ == "__main__": #Only when run as a script, so tests can import this file without opening a window
    if len(sys.argv) > 1: #Any command line arguments means CLI mode, no window
        sys.exit(run_cli())
    run_gui()
