def read_words(file_path):
    """
    Reads a file and returns a set of words.
    This function lowercases all words for case-insensitive comparison.
    """
    with open(file_path, 'r') as f:
        # Read the content and split into words based on whitespace
        text = f.read()
        # Optionally, you could use regex for more robust word extraction
        words = text.lower().split()
    return set(words)

def main():
    # Specify the paths to your text files
    file1 = 'phrases.txt'
    file2 = 'trustWallet.txt'
    
    # Read words from both files
    words1 = read_words(file1)
    words2 = read_words(file2)
    
    # Find common words and unique words
    common_words = words1.intersection(words2)
    unique_to_file1 = words1 - words2
    unique_to_file2 = words2 - words1

    # Display the results in the terminal
    print("Common words between the two files:")
    print(common_words)
    # print("\nWords unique to", file1 + ":")
    # print(unique_to_file1)
    # print("\nWords unique to", file2 + ":")
    # print(unique_to_file2)

if __name__ == '__main__':
    main()
