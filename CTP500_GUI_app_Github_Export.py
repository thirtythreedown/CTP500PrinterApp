'''
Bluetooth LE CTP500 thermal printer client by Mel at ThirtyThreeDown Studio
See https://thirtythreedown.com/2025/11/02/pc-app-for-walmart-thermal-printer/ for process and details!
Shout out to Bitflip, Tsathoggualware, Reid and all the mad lasses and lads whose research made this possible!

'''

#System imports
import socket
import sys
from time import sleep
import struct

#Tkinter imports
import tkinter as tk
from tkinter import Frame, Label, Button, Text, Radiobutton, messagebox
from tkinter.messagebox import showinfo
from tkinter import filedialog as fd
from tkinter import scrolledtext

#PILLOW imports
import PIL.Image
import PIL.ImageTk
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageChops
import PIL.ImageOps

#COMMUNICATION LOGIC STARTS HERE
mac_address = "00:00:00:00:00:00" #Put in your printer's Bluetooth device address here - you can find it in the app

class PrinterConnect: #Starting a PrinterConnect class to keep track of connection status
    def __init__(self):
        self.socket = None #Starting a disconnect socket
        self.connected = False #Setting socket status to False/disconnected

    def connect(self, mac_address): #Setting up a connection function
        if self.connected: #Checking to see if the printer is already connected
            print("Already connected") #Warning user
            return True #Switching PrinterConnect socket status

        try: #Starting all the things to do to establish a connection
            self.socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) #Setting up the Bluetooth socket with RFCOMM protocol
            self.socket.connect((mac_address, 1)) #Connection instruction with address and port to use

            print("Getting printer status")
            status = self.get_printer_status() #Calling the get_printer_status() function and storing it in status variable
            print(f'Printer status: {status}') #Displaying status variable

            self.connected = True #Switching connection status for tracking
            print("Connection established")
            return True #Returning status

        except Exception as e: #Exception handling in case something goes wrong
            print(f'Connection error: {e}')
            messagebox.showerror("Connection Error", f'Failed to connect with printer: {e}')
            if self.socket: #If the socket connection is present:
                self.socket.close() #Closing the connection
                self.socket = None #Clearing the socket references
            return False #Returning status

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
def create_text(text, font_name="Lucon.ttf", font_size=28):
    #Tweak to be able to change font w/ system fonts
    img = PIL.Image.new('RGB', (printerWidth, 5000), color=(255, 255, 255)) #Defines an RGB image, width is printer width, height is 5000px, color is white
    font = PIL.ImageFont.truetype(font_name, font_size) #Loads up font_name as the default font, at font_size default size

    d = PIL.ImageDraw.Draw(img) #Creates the d image object using the parameters above
    lines = [] #Creates an empty Python list to store lines of text
    for line in text.splitlines(): #Combing through text looking for line splits
        lines.append(get_wrapped_text(line, font, printerWidth)) #Creating a new lines list item at each line split
    lines = "\n".join(lines) #Recombining all the lines list items with a "\n" line jump instruction at each line break
    d.text((0, 0), lines, fill=(0, 0, 0), font=font) #Drawing our text onto our d object
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

def print_from_entry():
    txt = textInputField.get("1.0", tk.END).strip() # Grab the text from the scrolled‑text widget
    if not txt:
        messagebox.showwarning("No text", "Please type or load some text.")
        return

    img = create_text(txt) #Turning the text to image

    if printer.connected and printer.socket: #Send the text to the printer over the printer.socket (if connected)
        try:
            initializePrinter(printer.socket) #Initializing printer
            sleep(0.5)
            sendStartPrintSequence(printer.socket) #Starting up print sequence
            sleep(0.5)
            printImage(printer.socket, img) #Passing data to print
            sleep(0.5)
            sendEndPrintSequence(printer.socket) #Sending end of print sequence
            #messagebox.showinfo("Success", "Printed successfully.") #Optional success message
        except Exception as e:
            messagebox.showerror("Printing error", str(e))
    else:
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")

def print_from_image():
    """Send the currently loaded image to the printer."""
    if not current_image:
        messagebox.showwarning("No image", "Please load an image first.")
        return

    if not (printer.connected and printer.socket):
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")
        return

    try:
        print("Initializing printer")
        initializePrinter(printer.socket)
        sleep(0.5)

        print("Starting print sequence")
        sendStartPrintSequence(printer.socket)
        sleep(0.5)

        # THIS is where we actually hand the image over
        print("Printing image")
        printImage(printer.socket, current_image)

        print("Sending end sequence")
        sleep(0.5)
        sendEndPrintSequence(printer.socket)

        messagebox.showinfo("Success", "Image printed successfully.")
    except Exception as e:
        messagebox.showerror("Printing error", str(e))


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

def printImage(socket, im):
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
        return im.crop((bbox[0], bbox[1], bbox[2], bbox[3] + 10))  # Don't cut off the end of the image

def initializePrinter(soc):
    soc.send(b"\x1b\x40")

def sendStartPrintSequence(soc):
    #Check against hex dump
    soc.send(b"\x1d\x49\xf0\x19")

def sendEndPrintSequence(soc):
    #Check against hex dump. Missings \x9a?
    soc.send(b"\x0a\x0a\x0a\x9a")

#TEXT AND IMAGE INPUT RENDERING AND PRINTING ENDS HERE

#GUI SETUP STARTS HERE

root = tk.Tk()
frame = Frame(root)
frame.pack()

#Setting up window properties
root.title("CTP500 Printer Control")
root.configure() #Sets background color of the window. We will tweak this later to be able to select from printer colors and patterns
root.minsize(520, 600) #Sets min size of the window
root.geometry("520x600") #Changes original rendering position of the window

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
    command=lambda: printer.connect(mac_address),
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

#Creating our list of justification options
justification_options = ["left",
                 "center",
                 "right"]
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
